$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
python -m venv .buildenv
& '.\.buildenv\Scripts\python.exe' -m pip install -r requirements-build.txt
& '.\.buildenv\Scripts\python.exe' -m unittest discover -s . -p 'test_*.py' -v
& '.\.buildenv\Scripts\python.exe' -m PyInstaller --noconfirm --onefile --windowed --collect-all tkinterdnd2 --name '素材归档助手' app.py
Write-Output 'EXE generated in dist. Keep runtime and tools beside the EXE.'
