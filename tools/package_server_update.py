"""Package the locally prepared Winklar changes without publishing them."""
from pathlib import Path
import difflib
import shutil
import subprocess
import zipfile

root = Path(__file__).resolve().parents[1]
repo = root / "server" / "winklar"
destination = root / "server-update"
paths = [
    "app/Services/Schussreihenfolge.php", "app/Services/AbrechnungsService.php",
    "app/Services/RanglistenService.php", "app/Controllers/ClientApiController.php",
    "tests/serienwertung.php", "tests/schussreihenfolge.php", "tests/final.php", "tests/gabenabrechnung.php",
]
patches = []
for relative in paths:
    result = subprocess.run(["git", "-C", str(repo), "show", "HEAD:" + relative], capture_output=True)
    original = result.stdout.decode("utf-8") if result.returncode == 0 else ""
    changed = (repo / relative).read_text(encoding="utf-8")
    patches.append(f"diff --git a/{relative} b/{relative}\n")
    patches.extend(difflib.unified_diff(original.splitlines(True), changed.splitlines(True),
        fromfile="a/" + relative if result.returncode == 0 else "/dev/null", tofile="b/" + relative))
    target = destination / "files" / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(repo / relative, target)
(destination / "winklar-v2.patch").write_text("".join(patches), encoding="utf-8", newline="\n")
with zipfile.ZipFile(destination / "Winklar-V2-Update.zip", "w", zipfile.ZIP_DEFLATED) as archive:
    for relative in paths:
        archive.write(repo / relative, relative)
    archive.write(destination / "README.md", "V2-UPDATE-README.md")
print("Serverkorrektur gepackt: server-update/Winklar-V2-Update.zip")
