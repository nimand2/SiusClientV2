"""Read-only validation of an operator-supplied CSV. Never calls a real server."""
import json
from pathlib import Path
import shutil
import sys
import tempfile
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sius_client.core import Transfer
from test_transfer import FakeApi

source = Path(sys.argv[1])
with tempfile.TemporaryDirectory() as temp:
    root = Path(temp)
    sample = root / "frei-gewaehlter-dateiname.csv"
    shutil.copy2(source, sample)
    api = FakeApi()
    event = {"id": 1, "name": "Lokaler CSV-Test"}
    def transfer():
        return Transfer(api, event, sample, root / "Shooters.csv", root / "test.sqlite3", reference_date=datetime.fromtimestamp(source.stat().st_mtime).replace(hour=0, minute=0, second=0, microsecond=0))
    first = transfer()
    api.lose_response = True
    try:
        first.poll_shots()
    except Exception as exc:
        if "Antwort nach Speichern verloren" not in str(exc):
            raise
    restarted = transfer()
    restarted.prepare()
    restarted.poll_shots()
    state = restarted.snapshot()
    saved = len(api.saved)
    again = transfer()
    again.prepare()
    again.poll_shots()
    assert len(api.saved) == saved, "Wiederabgleich hat Duplikate erzeugt"
    assert state["queued"] == 0, "Offene Schüsse nach Wiederherstellung"
    payloads = list(api.saved.values())
    assert payloads == sorted(payloads, key=lambda s: (s["ZeitSeitJahresbeginn"], s["LogEvent"])), "Falsche Sendereihenfolge"
    report = {"datei": source.name, "zeilen": len(source.read_bytes().splitlines()),
              "bestaetigte_datensaetze": state["shots"], "ungueltige_zeilen": state["invalid"],
              "offen": state["queued"], "doppelte_nach_neustart": len(api.saved) - saved,
              "fruehester_schuss": payloads[0]["Zeit"] if payloads else None,
              "letzter_schuss": payloads[-1]["Zeit"] if payloads else None,
              "szenarien": ["Frei gewaehlter Dateiname", "Antwortverlust nach Speicherung", "Neustart", "Vollstaendiger Wiederabgleich", "Chronologische Sendereihenfolge"]}
    print(json.dumps(report, ensure_ascii=False, indent=2))
