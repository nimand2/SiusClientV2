"""Authorised live test for the supplied event, excluding start number 16."""
from datetime import datetime
import getpass
import json
from pathlib import Path
import shutil
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sius_client.core import Api, Transfer, parse_shot

SERVER = "https://winklarweb.emitprod.com"
SOURCE = Path("D:/LGS Wangen/fin/20261011.csv")
TARGET = Path("C:/Users/troge/Downloads/Shooters.csv")
run = Path("artifacts") / ("live-test-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
run.mkdir(parents=True)
report = {"server": SERVER, "anlass_id": 9, "ausgelassene_startnummer": 16, "bloecke": [], "laeufe": []}


class ObservedApi(Api):
    phase = ""

    def request(self, path, data=None):
        response = super().request(path, data)
        if path.endswith("/shots/import"):
            entry = {"lauf": self.phase, "gesendet": len(data["Shots"]), "antwort": response}
            report["bloecke"].append(entry)
            print(json.dumps(entry, ensure_ascii=False), flush=True)
            save_report()
        return response


def save_report():
    (run / "bericht.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")


def login(password):
    api = ObservedApi(SERVER)
    events = api.login("demo", password)
    event = next((e for e in events if e["id"] == 9 and e["name"] == "Chilbischiessen 2026"), None)
    if event is None:
        raise RuntimeError("Erwarteter Anlass nicht gefunden; keine Übertragung.")
    return api, event


def send(transfer):
    for attempt in range(3):
        try:
            transfer.poll_shots()
            return
        except Exception as exc:
            print(f"Versuch {attempt + 1}: {exc}", flush=True)
            if attempt == 2:
                raise
            time.sleep(2)


password = getpass.getpass("Passwort (wird nicht gespeichert): ")
try:
    api, event = login(password)
    rows = SOURCE.read_bytes().splitlines()
    selected, skipped = [], 0
    for raw in rows:
        if not raw.strip():
            continue
        if parse_shot(raw.decode("latin-1"))["StartNr"] == 16:
            skipped += 1
        else:
            selected.append(raw)
    if len(selected) != 1234 or skipped != 15:
        raise RuntimeError("Quelldatei hat sich seit der Vorprüfung verändert; Test gestoppt.")
    sample = run / "sius-test-ohne-nummer-16.csv"
    sample.write_bytes(b"\r\n".join(selected) + b"\r\n")
    report.update({"gepruefte_zeilen": len(selected), "ausgelassene_zeilen": skipped,
                   "quelle": str(SOURCE), "export": str(TARGET)})
    if TARGET.exists():
        backup = run / "Shooters-vor-Test.csv"
        shutil.copy2(TARGET, backup)
        report["export_sicherung"] = str(backup.resolve())
    for phase in ("Erster Abgleich", "Neustart und Wiederabgleich"):
        if report["laeufe"]:
            api, event = login(password)
        api.phase = phase
        transfer = Transfer(api, event, sample, TARGET, run / "warteschlange.sqlite3", datetime(2026, 10, 11))
        transfer.prepare()
        print(f"{phase}: Schützenliste exportiert, Schüsse werden abgeglichen.", flush=True)
        send(transfer)
        transfer.poll_shooters()
        state = transfer.snapshot()
        report["laeufe"].append({"lauf": phase, "bestaetigt": state["shots"], "offen": state["queued"],
                                 "ungueltig": state["invalid"], "schuetzen": state["shooters"]})
        if state["queued"] or state["invalid"] or state["shots"] != 1234:
            raise RuntimeError("Der Lauf wurde nicht vollständig bestätigt.")
        save_report()
    second = [b for b in report["bloecke"] if b["lauf"] == "Neustart und Wiederabgleich"]
    report["wiederholung_neu_eingefuegt"] = sum(b["antwort"]["imported"] for b in second)
    report["status"] = "erfolgreich" if report["wiederholung_neu_eingefuegt"] == 0 else "Duplikaterkennung prüfen"
    save_report()
    print(json.dumps({**report, "bericht": str((run / "bericht.json").resolve())}, ensure_ascii=False, indent=2), flush=True)
finally:
    password = None
