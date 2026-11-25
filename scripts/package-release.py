"""Create portable and source archives from explicit, credential-free inputs."""

import hashlib
import tomllib
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
version = tomllib.loads((root / "pyproject.toml").read_text("utf-8"))["project"]["version"]
dist = root / "dist"
binary = dist / "LinerParts"
if not (binary / "LinerParts.exe").exists():
    raise SystemExit("Build the Windows application first.")

portable = dist / f"LinerParts-{version}-windows-x64.zip"
with zipfile.ZipFile(portable, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
    for path in sorted(binary.rglob("*")):
        if path.is_file():
            archive.write(path, Path("LinerParts") / path.relative_to(binary))

source = dist / f"LinerParts-{version}-source.zip"
roots = ["src", "tests", "scripts", ".github", "docs", "installer"]
files = [
    "README.md",
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "pyproject.toml",
    "requirements-windows.lock",
    ".gitignore",
    "run_desktop.py",
    "frontend/package.json",
    "frontend/package-lock.json",
    "frontend/vite.config.js",
    "frontend/playwright.config.js",
    "frontend/index.html",
]
with zipfile.ZipFile(source, "w", zipfile.ZIP_DEFLATED) as archive:
    for folder in roots + ["frontend/src", "frontend/public", "frontend/tests"]:
        for path in sorted((root / folder).rglob("*")):
            if (
                path.is_file()
                and "__pycache__" not in path.parts
                and not any(part.endswith(".egg-info") for part in path.parts)
                and path.suffix != ".pyc"
            ):
                archive.write(path, Path("liner-desktop") / path.relative_to(root))
    for name in files:
        archive.write(root / name, Path("liner-desktop") / name)

lines = []
standalone = dist / "Agamaship-Desktop.exe"
for path in [portable, source] + ([standalone] if standalone.exists() else []):
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    lines.append(f"{digest}  {path.name}")
    print(f"{path.name}: {path.stat().st_size / 1024 / 1024:.2f} MB")
(dist / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", "utf-8")
