"""The Messenger API: send, mention, reply, attach, list threads, read new."""

from __future__ import annotations

import time

import pytest

from abt import messenger
from abt.errors import OpError

THREAD = "/messenger.html"


@pytest.fixture
def thread_url(base_url):
    return f"{base_url}{THREAD}"


def send(client, thread_url, **extra):
    body = {"thread_url": thread_url, "allow_any_host": True, **extra}
    return client.post("/messenger/sendmessage", json=body).json()


# --- message composition (no browser) -----------------------------------------


def test_segments_splits_around_mentions():
    assert messenger.segments("hi @Alice and @Bob!", ["Alice", "Bob"]) == [
        ("text", "hi "),
        ("mention", "Alice"),
        ("text", " and "),
        ("mention", "Bob"),
        ("text", "!"),
    ]


def test_segments_prefers_the_longer_name():
    # "@Anna" must not be read as "@Ann" plus a stray "a".
    assert messenger.segments("hey @Anna and @Ann", ["Ann", "Anna"]) == [
        ("text", "hey "),
        ("mention", "Anna"),
        ("text", " and "),
        ("mention", "Ann"),
    ]


def test_segments_without_mentions_is_one_piece():
    assert messenger.segments("plain text", []) == [("text", "plain text")]


def test_a_mention_missing_from_the_message_is_rejected():
    with pytest.raises(OpError) as exc:
        messenger.segments("no names here", ["Alice"])
    assert exc.value.type == "invalid_op"
    assert "@Alice" in exc.value.message


# --- request validation --------------------------------------------------------


def test_a_non_messenger_host_is_refused(client):
    body = client.post(
        "/messenger/sendmessage",
        json={"thread_url": "https://evil.example/t/1/", "message": "hi"},
    ).json()
    assert body["ok"] is False
    assert body["error"]["type"] == "invalid_op"
    assert "messenger.com" in body["error"]["message"]


def test_a_real_messenger_host_passes_validation():
    parsed = messenger.parse_send(
        {"thread_url": "https://www.messenger.com/t/123/", "message": "hi"}
    )
    assert parsed.thread_url.endswith("/t/123/")


def test_an_empty_message_with_no_attachments_is_refused(client):
    body = client.post(
        "/messenger/sendmessage",
        json={"thread_url": "https://www.messenger.com/t/1/", "message": "   "},
    ).json()
    assert body["error"]["type"] == "invalid_op"


def test_a_missing_attachment_file_is_refused(client, thread_url):
    body = send(client, thread_url, message="hi", attachments=["/no/such/file.png"])
    assert body["error"]["type"] == "invalid_op"
    assert "no such file" in body["error"]["message"]


# --- sending -------------------------------------------------------------------


def test_a_plain_message_lands_in_the_thread(client, thread_url):
    body = send(client, thread_url, message="hello there")
    assert body["ok"] is True, body
    result = body["result"]
    assert result["sent"] is True
    assert result["confirmed"] is True
    assert result["articles_after"] == result["articles_before"] + 1

    rows = client.get("/messenger/messages").json()["result"]["messages"]
    assert rows[-1]["text"] == "hello there"
    assert rows[-1]["sender"] == "You"


def test_a_stale_draft_is_cleared_before_typing(client, thread_url):
    client.post("/command-list", json={"op": "goto", "url": thread_url})
    client.post("/command-list", json={"op": "input", "css": "#composer", "value": "junk"})
    send(client, thread_url, message="clean")
    rows = client.get("/messenger/messages").json()["result"]["messages"]
    assert rows[-1]["text"] == "clean"


def test_a_mention_goes_through_the_suggestion_popup(client, thread_url):
    body = send(client, thread_url, message="ping @Carol", mentions=["Carol"])
    assert body["ok"] is True, body
    assert body["result"]["mentions"] == ["Carol Chase"]
    rows = client.get("/messenger/messages").json()["result"]["messages"]
    assert "Carol Chase" in rows[-1]["text"]


def test_a_mention_with_no_suggestion_sends_nothing(client, thread_url):
    body = send(client, thread_url, message="ping @Zeno", mentions=["Zeno"])
    assert body["ok"] is False
    assert body["error"]["type"] == "element_not_found"
    rows = client.get("/messenger/messages").json()["result"]["messages"]
    assert "Zeno" not in rows[-1]["text"]


def test_a_reply_quotes_the_message_it_answers(client, thread_url):
    body = send(client, thread_url, message="noon it is", reply_to="lunch tomorrow?")
    assert body["ok"] is True, body
    assert "lunch tomorrow?" in body["result"]["replied_to"]
    rows = client.get("/messenger/messages").json()["result"]["messages"]
    assert rows[-1]["text"].startswith("Re: lunch tomorrow?")


def test_a_reply_by_index_targets_that_row(client, thread_url):
    body = send(client, thread_url, message="indexed", reply_to=0)
    assert body["ok"] is True, body
    assert "lunch tomorrow?" in body["result"]["replied_to"]


def test_a_reply_to_a_message_that_is_not_there_sends_nothing(client, thread_url):
    body = send(client, thread_url, message="hi", reply_to="never said this")
    assert body["error"]["type"] == "element_not_found"


def test_an_attachment_is_staged_and_sent(client, thread_url, tmp_path):
    picture = tmp_path / "shot.png"
    picture.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    body = send(client, thread_url, message="look", attachments=[str(picture)])
    assert body["ok"] is True, body
    assert body["result"]["attachments"][0]["bytes"] == picture.stat().st_size
    assert body["result"]["attachments_staged"] == 1
    rows = client.get("/messenger/messages").json()["result"]["messages"]
    assert "[1 attachment(s)]" in rows[-1]["text"]


def test_an_http_attachment_is_downloaded_first(client, thread_url, base_url):
    body = send(
        client,
        thread_url,
        message="fetched",
        attachments=[f"{base_url}/cards.html"],
    )
    assert body["ok"] is True, body
    assert body["result"]["attachments"][0]["path"].endswith("cards.html")


# --- reading -------------------------------------------------------------------


def test_threads_lists_the_sidebar(client, thread_url):
    body = client.get("/messenger/threads", params={"url": thread_url}).json()
    threads = body["result"]["threads"]
    assert body["result"]["count"] == 2
    assert threads[0]["name"] == "Alice Aster"
    assert threads[0]["preview"] == "see you then"
    assert threads[0]["time"] == "10:14"
    assert threads[0]["url"].endswith("/t/100/")
    assert threads[1]["e2ee"] is True


def test_messages_are_parsed_into_sender_time_and_text(client, thread_url):
    client.post("/command-list", json={"op": "goto", "url": thread_url})
    rows = client.get("/messenger/messages").json()["result"]["messages"]
    assert len(rows) == 3
    assert rows[0] == {
        "text": "lunch tomorrow?",
        "sender": "Alice Aster",
        "time": "10:12",
        "raw": rows[0]["raw"],
    }


def test_since_last_returns_only_what_arrived_after(client, thread_url):
    first = client.get(
        "/messenger/messages",
        params={"thread_url": thread_url, "since_last": True, "reset": True},
    ).json()["result"]
    assert first["new"] == 3

    again = client.get(
        "/messenger/messages", params={"since_last": True}
    ).json()["result"]
    assert again["new"] == 0

    send(client, thread_url, message="fresh")
    after = client.get("/messenger/messages", params={"since_last": True}).json()["result"]
    assert after["new"] == 1
    assert after["messages"][0]["text"] == "fresh"
    assert after["total_on_screen"] == 4


def test_cursors_compare_by_content_not_position():
    cursors = messenger.MessageCursors()
    cursors.advance("https://x/t/1/", ["a", "b", "c"])
    # The thread scrolled and dropped its oldest row; only "d" is new.
    assert cursors.advance("https://x/t/1/", ["b", "c", "d"]) == ["d"]


def test_a_fragment_does_not_split_a_thread_cursor():
    cursors = messenger.MessageCursors()
    assert cursors.key("https://x/t/1/?a=1#top") == cursors.key("https://x/t/1/#bottom")


# --- background sends -----------------------------------------------------------


def test_a_background_send_answers_before_it_finishes(client, thread_url):
    body = client.post(
        "/messenger/sendmessage/async",
        json={"thread_url": thread_url, "message": "queued", "allow_any_host": True},
    ).json()
    assert body["ok"] is True
    job_id = body["result"]["job_id"]
    assert body["result"]["state"] in ("queued", "running", "sent")

    job = _await_job(client, job_id)
    assert job["state"] == "sent", job
    assert job["result"]["confirmed"] is True
    assert job["result"]["tab_id"].startswith("tab_")


def test_a_background_send_leaves_the_original_tab_in_front(client, thread_url, base_url):
    client.post("/command-list", json={"op": "goto", "url": f"{base_url}/cards.html"})
    body = client.post(
        "/messenger/sendmessage/async",
        json={"thread_url": thread_url, "message": "elsewhere", "allow_any_host": True},
    ).json()
    _await_job(client, body["result"]["job_id"])

    status = client.get("/status").json()["result"]
    assert status["url"].endswith("/cards.html")
    assert len(status["tabs"]) == 1


def test_a_failed_background_send_is_recorded_on_the_job(client, thread_url):
    body = client.post(
        "/messenger/sendmessage/async",
        json={
            "thread_url": thread_url,
            "message": "ping @Zeno",
            "mentions": ["Zeno"],
            "allow_any_host": True,
        },
    ).json()
    job = _await_job(client, body["result"]["job_id"])
    assert job["state"] == "failed"
    assert job["error"]["type"] == "element_not_found"


def test_an_unknown_job_is_a_404(client):
    response = client.get("/messenger/jobs/nope")
    assert response.status_code == 404


def test_jobs_lists_what_has_run(client, thread_url):
    client.post(
        "/messenger/sendmessage/async",
        json={"thread_url": thread_url, "message": "listed", "allow_any_host": True},
    )
    body = client.get("/messenger/jobs").json()
    assert len(body["result"]) >= 1


def _await_job(client, job_id, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = client.get(f"/messenger/jobs/{job_id}").json()["result"]
        if job["state"] in ("sent", "failed"):
            return job
        time.sleep(0.2)
    raise AssertionError(f"job {job_id} never finished")
