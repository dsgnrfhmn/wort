"""The Anthropic provider against a mock transport: no network, no key. It checks the request we send and how
every kind of reply and error is handled. Live behaviour is checked by scripts/ai_smoke.py on the server."""

import json
import logging

import pytest

httpx = pytest.importorskip("httpx2", reason="the 'ai' dependency group (anthropic SDK) is not installed")
pytest.importorskip("anthropic")

from app.ai import config as cfg  # noqa: E402
from app.ai import schemas, service  # noqa: E402
from app.ai.anthropic_provider import AnthropicProvider  # noqa: E402
from app.ai.provider import AiError  # noqa: E402
from app.db import WebStore  # noqa: E402

KEY = "sk-ant-api03-TESTKEYTESTKEYTESTKEY"
CHECK = {"errors": [{"wrong": "ein", "right": "einen", "kind": "Artikel"}],
         "word_results": [{"word": "Antrag", "ok": False, "note": "Akkusativ"}],
         "rule": "Artikel im Akkusativ", "natural": "Ich stelle einen Antrag.", "corrected": "Ich stelle einen Antrag."}


def message(payload, *, stop="end_turn", leading_thinking=True, text=None):
    content = ([{"type": "thinking", "thinking": "", "signature": "sig"}] if leading_thinking else [])
    content.append({"type": "text", "text": json.dumps(payload) if text is None else text})
    return {"id": "msg_1", "type": "message", "role": "assistant", "model": "claude-haiku-5-5", "content": content,
            "stop_reason": stop, "stop_sequence": None, "usage": {"input_tokens": 120, "output_tokens": 45}}


class Server:
    def __init__(self, reply=None, status=200, error=None):
        self.reply, self.status, self.error, self.requests = reply, status, error, []

    def __call__(self, request):
        self.requests.append(request)
        if self.error:
            raise self.error
        return httpx.Response(self.status, json=self.reply, headers={"request-id": "req_test"})


def provider(server, **over):
    config = cfg.AiConfig(enabled=True, api_key=KEY, daily_cap=10, **over)
    return AnthropicProvider(config, http_client=httpx.Client(transport=httpx.MockTransport(server))), server


def body(server):
    return json.loads(server.requests[-1].content)


def test_request_shape_for_every_block():
    sites = {
        "check_sentence": (lambda p: p.check_sentence("Ich stelle ein Antrag", ["Antrag"], "Akkusativ"), CHECK),
        "recheck": (lambda p: p.recheck("Ich stelle ein Antrag", ["Antrag"], "Akkusativ", "doch richtig"), CHECK),
        "explain": (lambda p: p.explain("Ich stelle ein Antrag", schemas.SentenceCheck(**CHECK)),
                    {"rule": "R", "explanation": "E", "merke": "M", "explanation_uk": "U"}),
        "generate_tasks": (lambda p: p.generate_tasks(["Haus"], 3),
                           {"tasks": [{"prompt": "Was?", "word": "Haus", "translation_uk": "Що?", "translation_en": "What?"}]}),
        "more_for_rule": (lambda p: p.more_for_rule("Akkusativ", 5),
                          {"tasks": [{"prompt": "Was?", "word": "Haus", "translation_uk": "Що?", "translation_en": "What?"}]}),
        "grade_answer": (lambda p: p.grade_answer("Was bedeutet Haus?", "house", "house; home"),
                         {"verdict": "richtig", "comment": "Gut."}),
    }
    for name, (call, reply) in sites.items():
        p, server = provider(Server(message(reply)))
        call(p)
        req = server.requests[-1]
        b = body(server)
        assert str(req.url) == "https://api.anthropic.com/v1/messages", name
        assert b["model"] == "claude-haiku-5-5", name
        for forbidden in ("temperature", "top_p", "top_k"):
            assert forbidden not in b, (name, forbidden)  # 400 on Haiku 5.5
        assert b["messages"][-1]["role"] == "user" and len(b["messages"]) == 1, name  # no prefill
        assert b["output_config"]["effort"] in {"low", "medium"} and b["output_config"]["format"]["type"] == "json_schema", name
        assert "Daten" in b["system"] and b["max_tokens"] >= 2048, name
        payload = json.loads(b["messages"][0]["content"])  # the user message is JSON data
        assert "request" in payload, name


def test_reply_with_leading_thinking_block_is_read_by_type():
    p, _ = provider(Server(message(CHECK, leading_thinking=True)))
    assert p.check_sentence("Ich stelle ein Antrag", ["Antrag"], "t").rule == "Artikel im Akkusativ"
    assert p.last_usage == (120, 45)


def test_base_url_cannot_be_redirected_by_the_environment(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://evil.example")
    p, server = provider(Server(message(CHECK)))
    p.check_sentence("Satz hier drei", ["w"], "t")
    assert server.requests[-1].url.host == "api.anthropic.com"


def test_only_whitelisted_sanitized_fields_are_sent():
    p, server = provider(Server(message(CHECK)))
    hostile = "Ich\x1b[31m sehe‮ <script>x</script> ```evil``` Haus\x00"
    p.check_sentence(hostile, ["Haus​"], "Aufgabe\x07")
    sent = json.loads(body(server)["messages"][0]["content"])
    assert set(sent) == {"request", "sentence", "words", "task"}
    text = json.dumps(sent, ensure_ascii=False)
    for bad in ("\x1b", "‮", "\x00", "​", "\x07", "<", ">", "```"):
        assert bad not in text
    assert KEY not in json.dumps(body(server))  # never in the body
    assert KEY in server.requests[-1].headers["authorization"]  # the key goes in the auth header only (SDK 2.x)


@pytest.mark.parametrize("stop,code", [("refusal", "refusal"), ("max_tokens", "truncated")])
def test_refusal_and_truncation_are_errors_not_verdicts(stop, code):
    p, _ = provider(Server(message(CHECK, stop=stop)))
    with pytest.raises(AiError, match=code):
        p.check_sentence("Satz hier drei", ["w"], "t")


@pytest.mark.parametrize("status,code", [(429, "rate_limited"), (401, "auth"), (403, "auth"), (400, "bad_request"),
                                         (500, "http_500"), (529, "http_529")])
def test_http_errors_map_to_fixed_codes_without_echoing_the_body(status, code, caplog):
    echo = "SECRET-SENTENCE-ECHO"
    p, _ = provider(Server({"type": "error", "error": {"type": "x", "message": echo}}, status=status))
    with caplog.at_level(logging.DEBUG), pytest.raises(AiError) as e:
        p.check_sentence("Satz hier drei", ["w"], "t")
    assert str(e.value) == code and echo not in str(e.value) and echo not in caplog.text
    assert KEY not in caplog.text


def test_network_errors_map_to_unreachable():
    p, _ = provider(Server(error=httpx.ConnectError("boom")))
    with pytest.raises(AiError, match="unreachable"):
        p.check_sentence("Satz hier drei", ["w"], "t")


@pytest.mark.parametrize("text", ["not json", "[]", json.dumps({"errors": "x"}), json.dumps({**CHECK, "extra": 1}),
                                  json.dumps({**CHECK, "rule": "x" * 400})])
def test_invalid_replies_are_rejected(text):
    p, _ = provider(Server(message(None, text=text)))
    with pytest.raises(schemas.AiInvalid):
        p.check_sentence("Satz hier drei", ["w"], "t")


@pytest.mark.parametrize("bad", ["<script>alert(1)</script>", "Siehe https://evil.example", "[x](http://e)", "{{7*7}}",
                                 "versteckt​text", "bidi‮flip"])
def test_unsafe_reply_content_is_rejected_by_the_service(tmp_path, bad):
    store = WebStore(tmp_path / "w.db")
    uid = store.create_user("a", "h").id
    reply = {**CHECK, "natural": bad}
    p, _ = provider(Server(message(reply)))
    svc = service.build(cfg.AiConfig(enabled=True, api_key=KEY, daily_cap=5), store, p)
    with pytest.raises(service.AiUnavailable) as e:
        svc.check_sentence(uid, "Satz hier drei", ["w"], "t")
    assert "ungültig" in e.value.reason


def test_safe_reply_passes_the_service(tmp_path):
    store = WebStore(tmp_path / "w.db")
    uid = store.create_user("a", "h").id
    p, _ = provider(Server(message(CHECK)))
    svc = service.build(cfg.AiConfig(enabled=True, api_key=KEY, daily_cap=5), store, p)
    assert svc.check_sentence(uid, "Ich stelle ein Antrag", ["Antrag"], "t").corrected == "Ich stelle einen Antrag."


def test_key_is_never_in_repr_or_logs(caplog):
    config = cfg.AiConfig(enabled=True, api_key=KEY, daily_cap=3)
    assert KEY not in repr(config)
    with caplog.at_level(logging.DEBUG):
        p, _ = provider(Server(message(CHECK)))
        p.check_sentence("Satz hier drei", ["w"], "t")
    assert KEY not in caplog.text
