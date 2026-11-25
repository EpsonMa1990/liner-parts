import io

import pytest
from reportlab.pdfgen import canvas

from liner_parts.service import Service


@pytest.fixture
def pdf_bytes():
    stream = io.BytesIO()
    pdf = canvas.Canvas(stream, pagesize=(600, 800))
    for runner, part in [("A1", "03"), ("B", "12")]:
        pdf.setFont("Helvetica", 32)
        pdf.drawString(50, 700, f"{runner}({part})")
        pdf.setFillColorRGB(1, 0, 0)
        pdf.rect(300, 600, 120, 80, fill=True, stroke=False)
        pdf.setFillColorRGB(0, 0, 1)
        pdf.rect(300, 100, 120, 80, fill=True, stroke=False)
        pdf.showPage()
    pdf.save()
    return stream.getvalue()


@pytest.fixture
def service(tmp_path, monkeypatch):
    # Never write test credentials into the user's real credential store.
    keys = {}
    monkeypatch.setattr("keyring.get_password", lambda service, account: keys.get(account))
    monkeypatch.setattr("keyring.set_password", lambda service, account, key: keys.update({account: key}))
    monkeypatch.setattr("keyring.delete_password", lambda service, account: keys.pop(account, None))
    instance = Service(tmp_path)
    yield instance
    instance.close()


@pytest.fixture
def task(service, pdf_bytes):
    return service.import_pdf(io.BytesIO(pdf_bytes), "模型说明书.pdf", "测试模型")


def box(box_id="box-1", **overrides):
    return {
        "id": box_id,
        "x": 0.05,
        "y": 0.07,
        "width": 0.3,
        "height": 0.1,
        "category": "头",
        "quantity": 1,
        "runner": "",
        "part_number": "",
        "raw_text": "",
        "note": "",
        "status": "pending",
        **overrides,
    }
