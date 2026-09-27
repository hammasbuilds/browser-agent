import json
import socket
import threading

import pytest

from browser_agent.llm import CachedClient, FakeClient, LLMUnavailableError, OllamaClient, cache_key

MSGS = [{"role": "user", "content": "hi"}]


def test_cache_serves_the_second_identical_call_without_the_model(tmp_path):
    fake = FakeClient(lambda m: '{"action": "done"}', model="qwen2.5:14b-instruct")
    client = CachedClient(fake, tmp_path)
    assert client.chat(MSGS, {"temperature": 0}) == '{"action": "done"}'
    assert client.chat(MSGS, {"temperature": 0}) == '{"action": "done"}'
    assert len(fake.calls) == 1 and (client.hits, client.misses) == (1, 1)
    (stored,) = list(tmp_path.rglob("*.json"))
    assert stored.parent.name == "qwen2.5_14b-instruct"  # ':' is not a legal Windows path char
    assert json.loads(stored.read_text())["response"] == '{"action": "done"}'


def test_cache_key_changes_with_model_prompt_or_options():
    base = cache_key("m", MSGS, {"t": 0})
    assert base == cache_key("m", [dict(MSGS[0])], {"t": 0})
    assert base != cache_key("n", MSGS, {"t": 0})
    assert base != cache_key("m", [{"role": "user", "content": "hi!"}], {"t": 0})
    assert base != cache_key("m", MSGS, {"t": 1})


def test_unreachable_ollama_is_a_clear_error_not_a_hang():
    client = OllamaClient(base_url="http://127.0.0.1:9", timeout_s=2, backoff_s=0.01)
    with pytest.raises(LLMUnavailableError, match="127.0.0.1:9"):
        client.chat(MSGS, {})


def _read_request(conn: socket.socket) -> None:
    """Read a whole HTTP request (headers and body) so closing never resets the client."""
    data = b""
    while b"\r\n\r\n" not in data:
        data += conn.recv(65536)
    head, _, body = data.partition(b"\r\n\r\n")
    length = next(
        int(line.split(b":")[1])
        for line in head.split(b"\r\n")
        if line.lower().startswith(b"content-length")
    )
    while len(body) < length:
        body += conn.recv(65536)


def _one_shot_server(mode: str, replies: int = 3) -> int:
    """A local socket that misbehaves like a crashing Ollama runner (never the real one)."""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(replies)
    port = srv.getsockname()[1]

    def reply(conn: socket.socket) -> None:
        _read_request(conn)
        if mode == "200error":
            body = b'{"error":"model runner has unexpectedly stopped"}'
            head = b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
            conn.sendall(head + str(len(body)).encode() + b"\r\n\r\n" + body)
        elif mode == "garbage":
            conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\n\r\nhello")
        elif mode == "halfline":
            conn.sendall(b"HTTP/1.1 20")
        conn.close()  # "drop": close without a word

    def run() -> None:
        for _ in range(replies):
            conn, _ = srv.accept()
            reply(conn)
        srv.close()

    threading.Thread(target=run, daemon=True).start()
    return port


@pytest.mark.parametrize("mode", ["drop", "200error", "garbage", "halfline"])
def test_every_transport_or_payload_failure_is_retried_then_one_clean_error(mode):
    port = _one_shot_server(mode)
    client = OllamaClient(base_url=f"http://127.0.0.1:{port}", timeout_s=2, backoff_s=0.01)
    with pytest.raises(LLMUnavailableError, match="failed 3 times"):
        client.chat(MSGS, {})


def test_a_stalled_reply_times_out_into_the_same_clean_error():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(3)  # accepts the connection but never answers
    client = OllamaClient(
        base_url=f"http://127.0.0.1:{srv.getsockname()[1]}",
        timeout_s=0.3,
        attempts=2,
        backoff_s=0.01,
    )
    with pytest.raises(LLMUnavailableError, match="failed 2 times"):
        client.chat(MSGS, {})
    srv.close()


def test_a_transient_failure_then_a_good_reply_succeeds():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(2)

    def run() -> None:
        conn, _ = srv.accept()
        _read_request(conn)
        conn.close()  # first attempt dropped
        conn, _ = srv.accept()
        _read_request(conn)
        body = json.dumps({"message": {"content": '{"action": "done"}'}}).encode()
        head = b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
        conn.sendall(head + str(len(body)).encode() + b"\r\n\r\n" + body)
        conn.close()
        srv.close()

    threading.Thread(target=run, daemon=True).start()
    client = OllamaClient(base_url=f"http://127.0.0.1:{srv.getsockname()[1]}", backoff_s=0.01)
    assert client.chat(MSGS, {}) == '{"action": "done"}'
