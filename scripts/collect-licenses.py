"""Collect bundled dependency notices into the Windows distribution."""

import importlib.metadata
import json
import shutil
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
output = root / "dist" / "LinerParts" / "licenses"
output.mkdir(parents=True, exist_ok=True)
inventory = []
for dist in importlib.metadata.distributions():
    name = dist.metadata.get("Name", "unknown")
    inventory.append(
        {
            "name": name,
            "version": dist.version,
            "license": dist.metadata.get("License-Expression")
            or dist.metadata.get("License", "See bundled notices"),
        }
    )
    for file in dist.files or []:
        if any(
            "license" in part.lower() or "notice" in part.lower() or part.lower() == "copying"
            for part in file.parts
        ):
            source = Path(dist.locate_file(file))
            if source.is_file() and source.suffix.lower() not in {".py", ".pyc", ".dll", ".exe"}:
                # Distributions may list paths outside site-packages; copy only safe relative names.
                relative = Path(*[part for part in file.parts if part not in ("..", ".")])
                target = output / "python-packages" / name / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
python_license = Path(sys.base_prefix) / "LICENSE.txt"
if python_license.exists():
    shutil.copyfile(python_license, output / "PYTHON-LICENSE.txt")
for name in [
    "vue",
    "@vue/shared",
    "@vue/reactivity",
    "@vue/runtime-core",
    "@vue/runtime-dom",
    "lucide-vue-next",
]:
    folder = root / "frontend" / "node_modules" / name
    for file in folder.glob("LICENSE*"):
        target = output / "frontend" / name / file.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(file, target)
    metadata = json.loads((folder / "package.json").read_text("utf-8"))
    inventory.append({"name": name, "version": metadata["version"], "license": metadata.get("license")})
(output / "DEPENDENCIES.json").write_text(json.dumps(inventory, ensure_ascii=False, indent=2), "utf-8")
print(f"Collected notices for {len(inventory)} installed distributions and frontend components.")
