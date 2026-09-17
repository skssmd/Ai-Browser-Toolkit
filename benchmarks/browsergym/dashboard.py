"""WebArena sweep dashboard. Serves on :9102.

Four tabs: All (every sweep + main run logs), Gitlab, Reddit, Multisite (the
queued cross-site gitlab+reddit pass). Every task row
is clickable and opens a detail pane with the episode record (answer, tokens,
cached %, op-success %, turns, ops, reward) and the live per-task run log --
what the model ran, received, said and answered -- updated while you watch.

Canonical JSON is GET /data (everything the page renders), GET
/task/<sweep>/<task_id> (one episode record + its trace text), GET
/logs/<sweep> (the sweep's run log tail).

Reads results/*/plan.json, episodes.jsonl, traces/ and /opt/webarena/bench/
sweep-*.log -- never writes into a sweep's files. Recomputed on a timer so an
open tab cannot load the machine the sweeps use.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

RESULTS = Path("/opt/webarena/bench/toolkit/results")
LOGS = Path("/opt/webarena/bench")
INTERVAL = 30.0
POLL = 15
TRACE_CAP = 262144

SETTLED = frozenset({"ok", "skipped_site"})
FAULTS = frozenset({"harness_error", "harness_timeout"})


def _log_path_for(sweep: str) -> Path:
    label = sweep[3:] if sweep.startswith("wa-") else sweep
    return LOGS / f"sweep-{label}.log"


def read_rows(out: Path) -> list[dict]:
    rows = []
    for path in sorted(out.glob("episodes*.jsonl")):
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    return rows


def best_rows(rows: list[dict]) -> list[dict]:
    best = {}
    for row in rows:
        key = str(row.get("task_id"))
        current = best.get(key)
        if current is None:
            best[key] = row
        elif row.get("status") in SETTLED and current.get("status") not in SETTLED:
            best[key] = row
        elif current.get("status") not in SETTLED:
            best[key] = row
    return list(best.values())


def log_tail(sweep: str, n: int = 40) -> dict:
    path = _log_path_for(sweep)
    try:
        data = path.read_bytes()[-8192:]
        lines = data.decode("utf-8", errors="replace").splitlines()[-n:]
        return {
            "file": path.name,
            "size": path.stat().st_size,
            "mtime": path.stat().st_mtime,
            "tail": lines,
        }
    except OSError:
        return {"file": path.name, "size": 0, "mtime": None, "tail": []}


def running_tasks(out: Path, records: list[dict]) -> list[str]:
    have = {str(r.get("task_id")) for r in records}
    traces = out / "traces"
    running = []
    if traces.is_dir():
        for p in sorted(traces.glob("*.log")):
            tid = p.stem
            if tid not in have:
                running.append(tid)
    return running


def summarize(out: Path) -> dict:
    plan = {}
    try:
        plan = json.loads((out / "plan.json").read_text(encoding="utf-8"))
    except Exception:
        pass
    rows = best_rows(read_rows(out))
    graded = [r for r in rows if r.get("status") == "ok"]
    passed = [r for r in graded if r.get("success")]
    skipped = [r for r in rows if r.get("status") == "skipped_site"]
    faults = [r for r in rows if r.get("status") in FAULTS]
    running = running_tasks(out, rows)
    attempted = [r for r in rows if r.get("status") != "skipped_site"]
    total_ops = sum(r.get("ops") or 0 for r in attempted)
    total_fail = sum(r.get("op_failures") or 0 for r in attempted)
    total_turns = sum(r.get("turns") or 0 for r in attempted)
    tokens = sum(r.get("total_tokens") or 0 for r in rows)
    cache_read = sum(r.get("cache_read_tokens") or 0 for r in rows)
    cache_input = sum(r.get("input_tokens") or 0 for r in rows)
    cache_share = 100 * cache_read / max(cache_input, 1)
    tasks = []
    for r in rows:
        tasks.append({
            "task": str(r.get("task_id")),
            "pass": bool(r.get("success")),
            "status": r.get("status"),
            "running": False,
            "turns": r.get("turns"),
            "ops": r.get("ops"),
            "tokens": r.get("total_tokens"),
            "cache_share": r.get("cache_share"),
            "op_success_rate": r.get("op_success_rate"),
            "ops_per_turn": r.get("ops_per_turn"),
            "answer": (str(r.get("answer_sent") or "")[:80]),
            "wall_s": r.get("wall_s"),
        })
    for tid in running:
        tasks.append({"task": tid, "pass": None, "status": "running",
                      "running": True})
    return {
        "plan": {
            "model": plan.get("model"),
            "provider": plan.get("provider"),
            "sites": plan.get("sites_running"),
            "server": plan.get("server"),
            "cdp_port": plan.get("cdp_port"),
            "max_turns": plan.get("max_turns"),
            "episodes": plan.get("episodes"),
            "created": plan.get("created"),
        },
        "stats": {
            "graded": len(graded),
            "passed": len(passed),
            "skipped": len(skipped),
            "faults": len(faults),
            "running": len(running),
            "rate": 100 * len(passed) / max(len(graded), 1),
            "ops": total_ops,
            "op_failures": total_fail,
            "op_success": 100 * (total_ops - total_fail) / max(total_ops, 1),
            "ops_per_turn": round(total_ops / max(total_turns, 1), 2),
            "ops_per_task": round(total_ops / max(len(attempted), 1)),
            "tokens": tokens,
            "tokens_per_task": round(tokens / max(len(graded), 1)),
            "cache_read": cache_read,
            "cache_share": cache_share,
        },
        "tasks": tasks,
        "log": log_tail(out.name),
    }


class State:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.data: dict = {"generated": None, "sweeps": {}}

    def refresh(self) -> None:
        sweeps = {}
        for out in sorted(RESULTS.iterdir()) if RESULTS.is_dir() else []:
            if not out.is_dir() or not (out / "plan.json").exists():
                continue
            try:
                sweeps[out.name] = summarize(out)
            except Exception as exc:
                sweeps[out.name] = {"error": str(exc)}
        with self.lock:
            self.data = {"generated": time.time(), "sweeps": sweeps}

    def snapshot(self) -> dict:
        with self.lock:
            return dict(self.data)


STATE = State()
STATE.refresh()


def _loop() -> None:
    while True:
        time.sleep(INTERVAL)
        try:
            STATE.refresh()
        except Exception:
            pass


def task_detail(sweep: str, task: str) -> dict:
    out = RESULTS / sweep
    record = None
    running = False
    rows = read_rows(out)
    for r in rows:
        if str(r.get("task_id")) == task:
            if record is None:
                record = r
            elif r.get("status") in SETTLED and record.get("status") not in SETTLED:
                record = r
            elif record.get("status") not in SETTLED:
                record = r
    trace = ""
    trace_mtime = None
    trace_path = out / "traces" / f"{task}.log"
    if trace_path.exists():
        trace_mtime = trace_path.stat().st_mtime
        trace_bytes = trace_path.read_bytes()[-TRACE_CAP:]
        trace = trace_bytes.decode("utf-8", errors="replace")
    if record is None:
        running = trace_path.exists()
    return {
        "sweep": sweep,
        "task": task,
        "record": record,
        "running": running,
        "trace": trace,
        "trace_bytes": len(trace),
        "trace_mtime": trace_mtime,
    }


PAGE = """<!doctype html><html><head><meta charset="utf-8">
<title>WebArena sweep dashboard</title>
<style>
:root{--bg:#101418;--panel:#171d24;--line:#2a333d;--txt:#d7dee6;--dim:#8b97a3;
--pass:#4ce08f;--fail:#ff6b6b;--skip:#c0a44a;--run:#5aa7ff;--head:#eaeff4}
*{box-sizing:border-box}
body{font-family:system-ui,Segoe UI,sans-serif;background:var(--bg);color:var(--txt);
margin:0;padding:1.25rem 1.5rem 4rem}
header{display:flex;align-items:baseline;gap:1.2rem;flex-wrap:wrap}
h1{font-size:1.25rem;color:var(--head);margin:0}
#updated{font-size:.78rem;color:var(--dim)}
nav{margin:.9rem 0 0;display:flex;gap:.4rem}
nav button{background:var(--panel);color:var(--dim);border:1px solid var(--line);
padding:.45rem 1rem;border-radius:6px 6px 0 0;cursor:pointer;font-size:.92rem}
nav button.on{color:var(--head);border-bottom-color:var(--bg);font-weight:600}
.tab{padding-top:1rem}
h2{font-size:1.02rem;color:var(--head);margin:1.2rem 0 .4rem}
.card{background:var(--panel);border:1px solid var(--line);border-radius:8px;
padding:.8rem 1rem;margin:.4rem 0}
.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(9.5rem,1fr));gap:1px;
background:var(--line);border:1px solid var(--line);border-radius:8px;overflow:hidden}
.metric{background:var(--panel);padding:.5rem .7rem}
.metric .k{font-size:.7rem;color:var(--dim);text-transform:uppercase;letter-spacing:.04em}
.metric .v{font-size:1.05rem;color:var(--head);margin-top:.15rem}
.grade{font-weight:700}
.pass{color:var(--pass)}.fail{color:var(--fail)}.skip{color:var(--skip)}.run{color:var(--run)}
table{border-collapse:collapse;width:100%;margin:.6rem 0 0;font-size:.82rem}
th,td{border:1px solid var(--line);padding:.35rem .55rem;text-align:left;white-space:nowrap}
th{color:var(--dim);font-weight:600;background:#12181f;position:sticky;top:0}
tbody tr{cursor:pointer}
tbody tr:hover{background:#1c242d}
td.ans{white-space:normal;max-width:26rem;overflow:hidden;text-overflow:ellipsis}
pre.log{background:#0c1014;border:1px solid var(--line);border-radius:8px;
padding:.8rem;font-size:.74rem;line-height:1.45;overflow:auto;white-space:pre-wrap;
word-break:break-word;max-height:60vh;color:#c9d4de}
.dim{color:var(--dim)}
a{color:var(--run)}
.modal{position:fixed;inset:0;background:rgba(0,0,0,.62);display:flex;z-index:50}
#panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;
margin:auto;width:min(1120px,96vw);max-height:94vh;display:flex;flex-direction:column}
#phead{padding:.8rem 1.1rem;border-bottom:1px solid var(--line);display:flex;
align-items:center;gap:1rem;flex-wrap:wrap}
#phead .x{margin-left:auto;background:none;border:1px solid var(--line);color:var(--dim);
border-radius:6px;cursor:pointer;padding:.25rem .6rem}
#pbody{padding:.9rem 1.1rem;overflow:auto;display:grid;grid-template-columns:1fr 1fr;
gap:1rem}
#pbody .full{grid-column:1/-1}
kbd{background:#0c1014;border:1px solid var(--line);border-radius:4px;
padding:0 .3rem;font-size:.78rem}
.hidden{display:none!important}
</style></head><body>
<header>
  <h1>WebArena sweeps</h1>
  <div id="updated">connecting…</div>
</header>
<nav>
  <button data-tab="all" class="on">All · main logs</button>
  <button data-tab="gitlab">Gitlab</button>
  <button data-tab="reddit">Reddit</button>
  <button data-tab="multisite">Multisite</button>
</nav>
<div class="tab" id="tab-all"></div>
<div class="tab hidden" id="tab-gitlab"></div>
<div class="tab hidden" id="tab-reddit"></div>
<div class="tab hidden" id="tab-multisite"></div>
<div class="modal hidden" id="modal"><div id="panel">
  <div id="phead"></div>
  <div id="pbody"></div>
</div></div>
<script>
const TABS=["all","gitlab","reddit","multisite"];
const SWEEPS={gitlab:"wa-gitlab",reddit:"wa-reddit",multisite:"wa-multisite"};
let state={sweeps:{}};let active="all";let openTask=null;let intvModal=null;const POLL=15;

function esc(s){return String(s==null?"":s).replace(/[&<>"']/g,c=>
 ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}
function fmt(n){return (n==null?"–":Number(n).toLocaleString());}
function pct(x){return (x==null?"–":(Number(x)*100).toFixed(1)+"%" );}
function badge(t){ if(t.running)return '<span class="run">RUNNING</span>';
  if(t.pass)return '<span class="pass">PASS</span>';
  if(t.status==="ok")return '<span class="fail">FAIL</span>';
  if(t.status==="skipped_site")return '<span class="skip">SKIP</span>';
  if(t.status==="harness_error"||t.status==="harness_timeout")return '<span class="fail">FAULT</span>';
  return '<span class="dim">'+esc(t.status||"?")+'</span>'; }

function summaryHTML(name,d){
  const p=d.plan||{},st=d.stats||{};
  let h='<h2>'+esc(name)+' '
    +'<span class="dim">· '+(p.model||"-")+' via '+(p.provider||"-")
    +' · max_turns '+(p.max_turns||"-")+' · server '+esc(p.server||"-")+'</span></h2>';
  h+='<div class="metrics">';
  const m=[["graded",fmt(st.graded)],
    ["passed",'<span class="'+(st.passed>=st.graded/2?"pass":"fail")+'">'+fmt(st.passed)+'</span>'],
    ["rate",'<span class="'+(st.rate>=50?"pass":"fail")+'">'+st.rate.toFixed(1)+'%</span>'],
    ["running",'<span class="run">'+fmt(st.running)+'</span>'],
    ["total tokens",fmt(st.tokens)],
    ["tokens/task",fmt(st.tokens_per_task)],
    ["cached",st.cache_share.toFixed(1)+'% <span class="dim">('+fmt(st.cache_read)+')</span>'],
    ["op success",st.op_success.toFixed(1)+'%'],
    ["ops/task",fmt(st.ops_per_task)],
    ["ops/turn",st.ops_per_turn==null?"–":st.ops_per_turn.toFixed(2)],
    ["skipped/faults",'<span class="skip">'+st.skipped+'</span>/<span class="fail">'+st.faults+'</span>']];
  for(const[k,v]of m){h+='<div class="metric"><div class="k">'+k+'</div><div class="v">'+v+'</div></div>';}
  h+='</div>';
  return h; }

function tasksTable(d){
  const ts=d.tasks&&d.tasks.length?d.tasks:[];
  const body=ts.map(t=>'<tr data-sweep="'+esc(d.name)+'" data-task="'+esc(t.task)+'">'
    +'<td>'+badge(t)+'</td>'
    +'<td>'+esc(t.task)+'</td>'
    +'<td class="ans">'+esc(t.answer||"")+'</td>'
    +'<td>'+fmt(t.turns)+'</td>'
    +'<td>'+fmt(t.ops)+'</td>'
    +'<td>'+fmt(t.ops_per_turn)+'</td>'
    +'<td>'+fmt(t.tokens)+'</td>'
    +'<td>'+pct(t.cache_share)+'</td>'
    +'<td>'+pct(t.op_success_rate)+'</td>'
    +'<td>'+(t.wall_s==null?"":t.wall_s+'s')+'</td>'
    +'</tr>').join("");
  return '<div class="card"><table><thead><tr><th>verdict</th><th>task</th>'
    +'<th>answer</th><th>turns</th><th>ops</th><th>ops/turn</th><th>tokens</th><th>cached</th>'
    +'<th>op %</th><th>wall</th></tr></thead><tbody>'
    +(body||'<tr><td colspan="10" class="dim">no episodes yet</td></tr>')
    +'</tbody></table></div>'; }

function logHTML(d){
  const lg=d.log||{};
  const lines=(lg.tail||[]).length?lg.tail.map(esc).join("\\n"):"(no run log yet)";
  return '<div class="card"><h2>Main run log — '+esc(lg.file||sweepOf(d.name))+'</h2>'
    +'<pre class="log" style="max-height:26vh">'+lines+'</pre></div>'; }

function sweepOf(name){return name==="wa-gitlab"?"gitlab":name==="wa-reddit"?"reddit":name==="wa-multisite"?"multisite":name;}

function renderAll(){
  let h="";
  for(const[name,d]of Object.entries(state.sweeps)){
    h+=summaryHTML(name,d)+tasksTable({name,tasks:d.tasks})+logHTML({name,log:d.log});
  }
  document.getElementById("tab-all").innerHTML=h||'<p class="dim">no sweeps yet</p>';
  return h; }

function renderOne(site){
  const name=SWEEPS[site];
  const d=state.sweeps[name];
  const el=document.getElementById("tab-"+site);
  if(!d){el.innerHTML='<p class="dim">no sweep '+site+' yet</p>';return;}
  el.innerHTML=summaryHTML(name,d)+tasksTable({name,tasks:d.tasks})+logHTML({name,log:d.log}); }

function render(){
  if(active==="all")renderAll();else renderOne(active);
  bindRows(); }

function bindRows(){
  document.querySelectorAll("tbody tr[data-task]").forEach(tr=>{
    tr.onclick=()=>taskModal(tr.getAttribute("data-sweep"),tr.getAttribute("data-task")); }); }

function taskModal(sweep,task){
  openTask={sweep,task};
  document.getElementById("modal").classList.remove("hidden");
  refreshTask();
  if(intvModal)clearInterval(intvModal);
  intvModal=setInterval(refreshTask,5000); }

function closeTask(){
  openTask=null;
  if(intvModal){clearInterval(intvModal);intvModal=null;}
  document.getElementById("modal").classList.add("hidden"); }

async function refreshTask(){
  if(!openTask)return;
  let j;
  try{j=await(await fetch("/task/"+openTask.sweep+"/"+openTask.task)).json();}
  catch(e){document.getElementById("pbody").innerHTML="<p>error "+e+"</p>";return;}
  const r=j.record||{},status=j.running?"running":(r.status||"?");
  const cls=j.running?"run":(r.success?"pass":(r.status==="skipped_site"?"skip":"fail"));
  const verdict=j.running?"RUNNING":(r.success?"PASS":(r.status==="ok"?"FAIL":
    (r.status==="skipped_site"?"SKIP":(r.status==="harness_error"||r.status==="harness_timeout"?"FAULT":esc(status)))));
  let head='<span class="'+cls+' grade">'+verdict+'</span>'
    +'<b>'+esc(j.task)+'</b>'
    +'<span class="dim">'+esc(j.sweep)+' · '+(j.running?"live":"final")+'</span>'
    +'<button class="x" onclick="closeTask()">close</button>';
  document.getElementById("phead").innerHTML=head;
  function tline(k,v){return '<tr><th>'+k+'</th><td>'+v+'</td></tr>';}
  const tokens='<div class="card"><b>Tokens &amp; cache</b><table><tbody>'
    +tline("total",fmt(r.total_tokens))
    +tline("input",fmt(r.input_tokens)+' <span class="dim">(cache_read '+fmt(r.cache_read_tokens)+')</span>')
    +tline("output",fmt(r.output_tokens))
    +tline("cached share",(r.cache_share==null?"–":(r.cache_share*100).toFixed(1)+"%"))
    +'</tbody></table></div>';
  const perf='<div class="card"><b>Run</b><table><tbody>'
    +tline("op success",(r.op_success_rate==null?"–":(r.op_success_rate*100).toFixed(1)+"%"))
    +tline("turns",fmt(r.turns))
    +tline("ops",fmt(r.ops))
    +tline("ops/turn",fmt(r.ops_per_turn))
    +tline("wall",(r.wall_s==null?"–":r.wall_s+"s")+' <span class="dim">model '+fmt(r.model_s)+"s</span>")
    +tline("hit_turn_limit",esc(r.hit_turn_limit))
    +tline('scored action','<code>'+esc(r.scored_action)+'</code>')
    +'</tbody></table></div>';
  const goal='<div class="card full"><b>Goal</b><p class="dim">'+esc(r.goal||"-")+'</p></div>';
  const ans='<div class="card full"><b>Answer sent</b><p>'+esc(j.running?"(running)":(r.answer_sent==null?"–":r.answer_sent))
    +'</p></div>';
  const reply='<div class="card full"><b>Full reply</b><pre class="log">'+esc(j.running?"":(r.reply||"(none)"))
    +'</pre></div>';
  const url='<div class="card full"><b>Final URL</b><p class="dim"><a href="'+esc(r.final_url)+'" target="_blank">'
    +esc(r.final_url||"-")+'</a></p></div>';
  const exp='<div class="card full"><b>Expected</b> <span class="dim">eval '
    +esc((r.eval_types||[]).join(" + ")||"-")
    +' · reference '+(r.reference_answer?"":"none")+'</span>'
    +'<pre class="log">'+esc(JSON.stringify(r.expected||{},null,1))+'</pre>'
    +'<b>Observed</b><pre class="log">'+esc(JSON.stringify(r.observed||{},null,1))+'</pre></div>';
  const logHeader='<div class="card full"><b>This task&apos;s run log</b> '
    +'<span class="dim">what it ran · what it received · what it said · what it answered'
    +(j.running?" · refreshing live":"")+'</span>'
    +'<pre class="log" style="max-height:42vh">'+esc(j.trace||"(no trace yet)")+'</pre></div>';
  document.getElementById("pbody").innerHTML=tokens+perf+goal+ans+reply+url+exp+logHeader;
}

function tick(){
  fetch("/data").then(r=>r.json()).then(j=>{
    state=j;
    const s=new Date(j.generated*1000).toLocaleString();
    document.getElementById("updated").textContent="updated "+s+" · poll "+POLL+"s";
    render();
  }).catch(e=>document.getElementById("updated").textContent="err "+e);
}

document.querySelectorAll("nav button").forEach(b=>{
  b.onclick=()=>{active=b.getAttribute("data-tab");
    document.querySelectorAll("nav button").forEach(x=>x.classList.toggle("on",x===b));
    TABS.forEach(t=>document.getElementById("tab-"+t).classList.toggle("hidden",t!==active));
    render();}; });
document.getElementById("modal").addEventListener("click",e=>{if(e.target.id==="modal")closeTask();});
document.addEventListener("keydown",e=>{if(e.key==="Escape")closeTask();});
setInterval(tick,POLL*1000);tick();
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj: dict) -> None:
        self._send(code, json.dumps(obj).encode("utf-8"), "application/json")

    def _bad(self, msg: str) -> None:
        self._json(404, {"error": msg})

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
        elif path == "/data":
            self._json(200, STATE.snapshot())
        elif path.startswith("/task/"):
            parts = path.split("/")
            if len(parts) != 4:
                return self._bad("bad task path")
            _, _, sweep, task = parts
            if sweep not in STATE.snapshot()["sweeps"]:
                return self._bad("unknown sweep " + sweep)
            if not _safe(task):
                return self._bad("bad task id")
            self._json(200, task_detail(sweep, task))
        elif path.startswith("/logs/"):
            sweep = path.split("/")[2]
            if sweep not in STATE.snapshot()["sweeps"]:
                return self._bad("unknown sweep " + sweep)
            self._json(200, {"sweep": sweep, "log": log_tail(sweep)})
        else:
            self._bad("not found")


def _safe(part: str) -> bool:
    return bool(part) and all(c.isalnum() or c in "._-" for c in part)


def main() -> None:
    threading.Thread(target=_loop, daemon=True).start()
    server = ThreadingHTTPServer(("127.0.0.1", 9102), Handler)
    print("dashboard on :9102", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()