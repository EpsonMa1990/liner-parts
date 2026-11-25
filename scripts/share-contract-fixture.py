"""Generate a synthetic PNG/JSON share ZIP for the Go protocol compatibility test."""

import argparse
import tempfile
from pathlib import Path

from liner_parts.service import Service

parser = argparse.ArgumentParser()
parser.add_argument("output", type=Path)
args = parser.parse_args()
with tempfile.TemporaryDirectory(prefix="liner-share-contract-") as directory:
    service = Service(Path(directory))
    try:
        task = service.demo()
        for i, page in enumerate(task["pages"]):
            page = service.save_page(
                page["id"],
                [
                    {
                        "id": f"contract-{i}",
                        "x": 0.1,
                        "y": 0.1,
                        "width": 0.3,
                        "height": 0.1,
                        "category": "头",
                        "runner": "A1",
                        "part_number": "003",
                        "quantity": 2,
                        "status": "manual",
                    }
                ],
                page["revision"],
            )
            service.sharing.confirm_page(page["id"], {"revision": page["revision"]})
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(
            service.sharing.package("协议测试模型", [service.page(p["id"]) for p in task["pages"]])
        )
        print(f"Synthetic share fixture: {args.output}")
    finally:
        service.close()
