"""Build the single-file Windows application using the already-built UI and notices."""
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files

root = Path(SPECPATH).parent
datas = collect_data_files('liner_parts')
binaries = []
hiddenimports = ['keyring.backends.Windows']
for package in ['webview', 'pypdfium2', 'pypdfium2_raw']:
    package_data, package_binaries, package_imports = collect_all(package)
    datas += package_data
    binaries += package_binaries
    hiddenimports += package_imports
datas += [
    (str(root / 'dist/LinerParts/licenses'), 'licenses'),
    (str(root / 'docs'), 'docs'),
    (str(root / 'LICENSE'), '.'),
    (str(root / 'THIRD_PARTY_NOTICES.md'), '.'),
]
analysis = Analysis(
    [str(root / 'run_desktop.py')], pathex=[str(root / 'src')],
    binaries=binaries, datas=datas, hiddenimports=hiddenimports,
)
# Windows 10/11 always use the operating system's Universal CRT.
analysis.binaries = [entry for entry in analysis.binaries if entry[0].lower() != 'ucrtbase.dll']
archive = PYZ(analysis.pure)
app = EXE(
    archive, analysis.scripts, analysis.binaries, analysis.datas, [],
    name='Agamaship-Desktop', console=False, icon=str(root / 'frontend/public/logo.ico'),
)
