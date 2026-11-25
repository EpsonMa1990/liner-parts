import io
import json
import threading

import httpx
import pytest
from PIL import Image

from liner_parts.recognition import RecognitionError, Recognizer, parse_result
from liner_parts.server import create_app
from liner_parts.settings import Settings, normalize_url


def png():
    out = io.BytesIO()
    with Image.new("RGB", (100, 50), "white") as image:
        image.save(out, "PNG")
    return out.getvalue()


@pytest.mark.parametrize(
    "payload",
    [
        {"items": []},
        {"items": [{"box_id": "wrong", "status": "recognized"}]},
        {"items": [{"box_id": "a", "runner": "A", "part_number": 3, "status": "recognized"}]},
        {"items": [{"box_id": "a", "runner": "A", "part_number": "3", "status": "made-up"}]},
    ],
)
def test_reject_malformed_model_results(payload):
    with pytest.raises(RecognitionError):
        parse_result(json.dumps(payload), {"a"})


def test_unknown_requires_review():
    result = parse_result(
        '```json\n{"items":[{"box_id":"a","runner":null,"part_number":"03","status":"recognized"}]}\n```',
        {"a"},
    )
    assert result["a"]["status"] == "review"


def test_retry_rate_limits_but_not_credentials(service):
    config = {**service.settings.snapshot(), "model": "test", "api_key": "private"}
    attempts = []

    class NoWait:
        def is_set(self):
            return False

        def wait(self, seconds):
            pass

    def limited(request):
        attempts.append(1)
        return httpx.Response(429, json={"error": {"message": "private"}})

    client = Recognizer(config, httpx.MockTransport(limited))
    with pytest.raises(RecognitionError) as exc:
        client.recognize([("a", png())], NoWait())
    client.close()
    assert len(attempts) == 3 and "private" not in str(exc.value)
    attempts.clear()

    def denied(request):
        attempts.append(1)
        return httpx.Response(401)

    client = Recognizer(config, httpx.MockTransport(denied))
    with pytest.raises(RecognitionError):
        client.recognize([("a", png())], threading.Event())
    client.close()
    assert len(attempts) == 1


def test_settings_key_isolation_and_no_plaintext(service):
    first = service.settings.save(
        {"base_url": "https://one.example/v1", "api_key": "secret-1", "model": "vision"}
    )
    assert first["has_key"] and "api_key" not in first
    assert "secret-1" not in service.settings.path.read_text("utf-8")
    service.settings.save({"base_url": "https://two.example/v1"})
    assert service.settings.key() == ""
    service.settings.save({"base_url": "https://one.example/v1"})
    assert service.settings.key() == "secret-1"
    service.settings.save({"clear_key": True})
    assert not service.settings.public()["has_key"]


def test_migrate_old_batch_size_without_changing_custom_prompt(service):
    service.settings.path.write_text(json.dumps({"batch_size": 4, "prompt": "my custom prompt"}), "utf-8")
    settings = Settings(service.store.root)
    assert settings.snapshot()["batch_size"] == 10
    assert settings.snapshot()["prompt"] == "my custom prompt"
    assert settings.save({"batch_size": 2})["batch_size"] == 10


def test_truncated_model_output_is_reported(service):
    client = Recognizer(
        service.settings.snapshot(),
        httpx.MockTransport(
            lambda request: httpx.Response(
                200, json={"choices": [{"finish_reason": "length", "message": {"content": "{"}}]}
            )
        ),
    )
    try:
        with pytest.raises(RecognitionError, match="输出被截断"):
            client.recognize([("a", png())], threading.Event())
    finally:
        client.close()


def test_url_normalization():
    assert normalize_url("https://example.com") == "https://example.com/v1"
    assert normalize_url("https://example.com/v1/chat/completions/") == "https://example.com/v1"
    assert normalize_url("http://127.0.0.1:1234/v1") == "http://127.0.0.1:1234/v1"
    for url in [
        "http://example.com/v1",
        "https://user:secret@example.com/v1",
        "https://example.com/?key=secret",
        "file:///tmp",
    ]:
        with pytest.raises(ValueError):
            normalize_url(url)


def test_local_server_auth_origin_and_csrf(service, task):
    app = create_app(service, "test-token-very-long")
    client = app.test_client()
    assert client.get("/api/tasks").status_code == 401
    assert client.get("/session?token=wrong").status_code == 401
    assert client.get("/session?token=test-token-very-long").status_code == 302
    assert client.get("/api/tasks").json[0]["id"] == task["id"]
    assert client.get("/api/settings", headers={"Host": "evil.example"}).status_code == 403
    assert client.post("/api/tasks/demo").status_code == 403
    assert (
        client.post(
            "/api/tasks/demo", headers={"X-Liner-Client": "desktop", "Origin": "https://evil.example"}
        ).status_code
        == 403
    )
    assert (
        client.put("/api/settings", json={"model": "test"}, headers={"X-Liner-Client": "desktop"}).status_code
        == 200
    )
    assert client.get("/api/tasks/unknown").status_code == 404
    assert client.get("/api/tasks/" + task["id"] + "/export/xlsx").status_code == 200
