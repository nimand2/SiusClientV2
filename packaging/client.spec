# Reproducible single-file Windows build. Qt uses native Windows ICU;
# unrelated versioned ICU DLLs from build tools must never be bundled.
from pathlib import Path

project = Path(SPECPATH).parent
a = Analysis([str(project / 'main.py')], pathex=[str(project)],
             binaries=[], datas=[], hiddenimports=[], hookspath=[], hooksconfig={},
             runtime_hooks=[], excludes=[], noarchive=False, optimize=0)
a.binaries = [entry for entry in a.binaries
              if not Path(entry[0]).name.lower().startswith('icu')]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='SiusClientV2',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=True,
          console=False, disable_windowed_traceback=False)
