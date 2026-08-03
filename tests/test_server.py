"""The HTTP surface: response envelope, batching, and stop-on-error."""

from __future__ import annotations


def test_single_command(client, base_url):
    body = client.post("/command", json={"op": "goto", "url": f"{base_url}/form.html"}).json()
    assert body["ok"] is True
    assert body["result"]["title"] == "Form"


def test_find_over_http_returns_shells(client):
    body = client.post("/command", json={"op": "find", "css": ".card"}).json()
    assert body["result"]["count"] == 3
    assert body["result"]["matches"][0]["html"].endswith("></div>")


def test_error_envelope_has_a_typed_error(client):
    body = client.post("/command", json={"op": "click", "css": "#ghost"}).json()
    assert body["ok"] is False
    assert body["error"]["type"] == "element_not_found"
    assert body["error"]["op_index"] == 0


def test_unknown_op_is_rejected_before_the_browser(client):
    body = client.post("/command", json={"op": "teleport"}).json()
    assert body["error"]["type"] == "invalid_op"


def test_malformed_json_is_a_400(client):
    response = client.post(
        "/command", content=b"{not json", headers={"content-type": "application/json"}
    )
    assert response.status_code == 400
    assert response.json()["error"]["type"] == "invalid_op"


def test_batch_runs_in_order(client, base_url):
    body = client.post(
        "/commands",
        json=[
            {"op": "goto", "url": f"{base_url}/form.html"},
            {"op": "input", "css": "#name", "value": "zoe"},
            {"op": "select", "css": "#size", "value": "l"},
            {"op": "click", "css": "#go"},
            {"op": "get_text", "css": "#out"},
        ],
    ).json()
    assert body["ok"] is True
    assert body["ran"] == 5
    assert body["results"][-1]["result"] == "zoe/l"


def test_batch_stops_on_first_error(client, base_url):
    body = client.post(
        "/commands",
        json=[
            {"op": "goto", "url": f"{base_url}/form.html"},
            {"op": "click", "css": "#ghost"},
            {"op": "input", "css": "#name", "value": "never"},
        ],
    ).json()
    assert body["ok"] is False
    assert body["ran"] == 2
    assert body["total"] == 3
    assert body["error"]["type"] == "element_not_found"
    assert body["error"]["op_index"] == 1


def test_batch_can_continue_on_error(client, base_url):
    body = client.post(
        "/commands",
        json={
            "commands": [
                {"op": "goto", "url": f"{base_url}/form.html"},
                {"op": "click", "css": "#ghost"},
                {"op": "input", "css": "#name", "value": "still ran"},
            ],
            "continue_on_error": True,
        },
    ).json()
    assert body["ok"] is False
    assert body["ran"] == 3
    assert body["results"][2]["ok"] is True
    assert body["results"][2]["result"]["value"] == "still ran"


def test_batch_body_must_be_a_list(client):
    response = client.post("/commands", json={"commands": "nope"})
    assert response.status_code == 400
    assert response.json()["error"]["type"] == "invalid_op"


def test_status_reports_the_session(client):
    body = client.get("/status").json()
    assert body["ok"] is True
    assert body["result"]["title"] == "Cards"
    assert body["result"]["active_tab"].startswith("tab_")
    assert body["result"]["headless"] is True


def test_status_counts_live_refs(client):
    assert client.get("/status").json()["result"]["refs_valid"] == 0
    client.post("/command", json={"op": "find", "css": ".card"})
    assert client.get("/status").json()["result"]["refs_valid"] == 3


def test_ops_endpoint_lists_every_op(client):
    from abt.ops import REGISTRY

    assert client.get("/ops").json()["result"] == sorted(REGISTRY)


def test_find_then_click_by_ref_over_http(client, base_url):
    client.post("/command", json={"op": "goto", "url": f"{base_url}/form.html"})
    found = client.post("/command", json={"op": "find", "css": "#go"}).json()
    ref = found["result"]["matches"][0]["ref"]
    body = client.post("/command", json={"op": "click", "ref": ref}).json()
    assert body["ok"] is True


def test_run_js_returns_a_value(client):
    body = client.post(
        "/command", json={"op": "run_js", "script": "return arguments[0] * 2;", "args": [21]}
    ).json()
    assert body["result"]["value"] == 42


def test_run_js_error_is_typed(client):
    body = client.post("/command", json={"op": "run_js", "script": "boom();"}).json()
    assert body["error"]["type"] == "js_error"
