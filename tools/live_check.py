"""Explicit operator-run live connection check; never stores credentials."""
from collections import Counter
from datetime import datetime
import getpass
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sius_client.core import Api, anchor_shot_time, parse_shot

api = Api("https://winklarweb.emitprod.com")
password = getpass.getpass("Passwort (wird nicht gespeichert): ")
try:
    try:
        events = api.login("demo", password)
    except Exception as exc:
        cause = exc.__cause__
        if hasattr(cause, "read"):
            import re
            body = cause.read().decode("utf-8", errors="replace")
            title = re.search(r"<title>(.*?)</title>", body, re.I | re.S)
            try:
                details = json.loads(body)
            except ValueError:
                details = {}
            print(json.dumps({"status": getattr(cause, "code", None),
                "content_type": cause.headers.get("Content-Type"),
                "server": cause.headers.get("Server"),
                "seite": title[1] if title else "keine HTML-Titelseite",
                "challenge": "challenge" in body.lower(),
                "errorCode": str(details.get("errorCode", "")).replace(password, "[entfernt]"),
                "message": str(details.get("message", "")).replace(password, "[entfernt]")}, ensure_ascii=False))
        raise SystemExit(str(exc))
finally:
    password = None
source = Path("D:/LGS Wangen/fin/20261011.csv")
payload = source.read_bytes()
shots, errors = [], []
for number, raw in enumerate(payload.split(b"\n")[:-1], 1):
    if not raw.strip():
        continue
    try:
        shots.append(anchor_shot_time(parse_shot(raw.decode("latin-1").rstrip("\r")), datetime(2026, 10, 11)))
    except Exception as exc:
        errors.append({"zeile": number, "fehler": str(exc)})
ids = set(s["StartNr"] for s in shots if s["StartNr"] > 0)
summary = {"anmeldung": "erfolgreich", "datei": str(source), "gueltige_zeilen": len(shots),
           "ungueltige_zeilen": errors, "startnummern": sorted(ids),
           "schussarten": dict(Counter(s["Schussart"] for s in shots)),
           "unvollstaendiges_dateiende": bool(payload and not payload.endswith(b"\n")),
           "anlaesse": []}
for event in events:
    shooters = api.request(f"/api/anlaesse/{event['id']}/shooters")
    known = {s.get("id", s.get("Id")) for s in shooters}
    summary["anlaesse"].append({**event, "schuetzen": len(shooters), "passende_nummern": len(ids & known),
                               "unbekannte_nummern": sorted(ids - known)})
Path("artifacts/live-vorpruefung.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
print(json.dumps(summary, indent=2, ensure_ascii=False))
