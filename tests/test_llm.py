import json

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
    client = OllamaClient(base_url="http://127.0.0.1:9", timeout_s=2)
    with pytest.raises(LLMUnavailableError, match="127.0.0.1:9"):
        client.chat(MSGS, {})
