"""Isolated local E2E fixture: no real provider requests or system credentials."""

import io
import json
import tempfile
import threading
import time
from pathlib import Path

import httpx
import keyring
from flask import jsonify, request
from PIL import Image, ImageDraw, ImageFont
from reportlab.pdfgen import canvas
from waitress import create_server

from liner_parts.recognition import Recognizer
from liner_parts.server import create_app
from liner_parts.service import Service

held_requests = {}
held_lock = threading.Lock()
share_receipt = {"id": 601, "model_name": "MG 测试机体", "status": "pending", "post_id": 0, "review_note": ""}


def mock_platform(request):
    path = request.url.path
    if path.endswith("/auth/password/login"):
        return httpx.Response(200, json={"code": 200, "data": {"token": "fixture-platform-jwt"}})
    if request.headers.get("Authorization") != "Bearer fixture-platform-jwt":
        return httpx.Response(401)
    if path.endswith("/auth/me"):
        data = {"id": 7, "name": "测试分享作者", "has_password": True}
    elif path.endswith("/capabilities"):
        data = {"version": 1, "reward_cards": 5}
    elif path.endswith("/desktop-submissions") and request.method == "POST":
        assert b"PK\x03\x04" in request.content
        data = share_receipt
    elif path.endswith("/desktop-submissions/601"):
        data = share_receipt
    else:
        return httpx.Response(404)
    return httpx.Response(200, json={"code": 200, "data": data})


def mock_openai(request):
    if request.url.path.endswith("/models"):
        return httpx.Response(200, json={"data": [{"id": "fixture-vision"}]})
    data = json.loads(request.content)
    items = []
    content = data["messages"][1]["content"]
    assert [item["type"] for item in content] == ["text", "image_url"]
    rows = json.loads(content[0]["text"])["rows"]
    assert 1 <= len(rows) <= 10
    number = "12"
    if data["model"] == "fixture-held":
        with held_lock:
            gate = threading.Event()
            held_requests[rows[0]["box_id"]] = gate
            number = f"{len(held_requests):02}"
        assert gate.wait(45), "E2E must release the held request"
    else:
        time.sleep(0.4)
    for row in rows:
        items.append(
            {
                "box_id": row["box_id"],
                "runner": "A",
                "part_number": number,
                "status": "recognized",
                "raw_text": "A(12)",
                "note": "",
            }
        )
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({"items": items})}}]})


if __name__ == "__main__":
    keyring.get_password = lambda *args: None
    keyring.set_password = lambda *args: None
    keyring.delete_password = lambda *args: None
    artifacts = Path(__file__).resolve().parents[1] / "artifacts"
    artifacts.mkdir(exist_ok=True)
    out = io.BytesIO()
    pdf = canvas.Canvas(out, pagesize=(600, 800))
    for number in (1, 2):
        pdf.setFont("Helvetica-Bold", 28)
        pdf.drawString(50, 735, f"LINER / TEST PAGE {number}")
        pdf.setFont("Helvetica", 24)
        pdf.drawString(80, 650, "A(12)")
        pdf.rect(80, 400, 230, 150)
        pdf.showPage()
    pdf.save()
    (artifacts / "e2e-manual.pdf").write_bytes(out.getvalue())
    for number in (2, 10, 11):
        with Image.new("RGB", (600, 800), "white") as image:
            draw = ImageDraw.Draw(image)
            draw.text((40, 40), f"IMAGE PAGE {number}", fill="black", font=ImageFont.load_default(size=28))
            draw.text((80, 130), "A(12)", fill="black", font=ImageFont.load_default(size=32))
            draw.rectangle((80, 350, 350, 520), outline="black", width=2)
            image.save(artifacts / f"e2e-page-{number}.png")
    with tempfile.TemporaryDirectory(prefix="liner-e2e-") as directory:
        service = Service(
            Path(directory), lambda config: Recognizer(config, httpx.MockTransport(mock_openai))
        )
        app = create_app(service, "e2e-local-token")
        service.sharing.transport = httpx.MockTransport(mock_platform)

        @app.post("/api/test/share-review")
        def share_review():
            share_receipt.update(status="approved", post_id=901)
            return jsonify(ok=True)

        @app.get("/api/test/held-requests")
        def held():
            with held_lock:
                return jsonify(list(held_requests))

        @app.post("/api/test/release")
        def release():
            key = (request.get_json() or {}).get("box_id")
            with held_lock:
                for box_id, gate in held_requests.items():
                    if not key or box_id == key:
                        gate.set()
            return jsonify(ok=True)

        app.config["LOCAL_HOST"] = "127.0.0.1:17654"
        server = create_server(app, host="127.0.0.1", port=17654, threads=6)
        try:
            server.run()
        finally:
            server.close()
            service.close()
