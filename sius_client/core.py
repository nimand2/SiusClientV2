"""SIUS protocol and file transfer. No GUI dependencies; independently testable."""

from __future__ import annotations

import csv
from datetime import datetime, timedelta
import io
import json
import math
import os
from pathlib import Path
import re
import tempfile
import threading
import time
from .journal import Journal
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler


class ClientError(Exception):
    """An error that can be displayed directly to the operator."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Do not forward passwords or bearer tokens to a redirect destination.
        return None


def normalise_url(value: str) -> str:
    value = value.strip().rstrip("/")
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError as exc:
        raise ClientError("Die Server-Adresse ist ungültig.") from exc
    if (parts.scheme not in ("http", "https") or not parts.hostname
            or parts.username or parts.password or parts.query or parts.fragment
            or any(c.isspace() for c in value)):
        raise ClientError("Bitte eine Server-Adresse mit http:// oder https:// eingeben.")
    return value


def lower_keys(item: dict) -> dict:
    if not isinstance(item, dict):
        raise ClientError("Der Server hat einen ungültigen Datensatz geliefert.")
    return {k.lower(): v for k, v in item.items()}


def records(data) -> list[dict]:
    if not isinstance(data, list):
        raise ClientError("Der Server hat keine gültige Liste geliefert.")
    return [lower_keys(item) for item in data]


class Api:
    def __init__(self, url: str):
        self.url = normalise_url(url)
        self.token = ""

    def request(self, path: str, data=None):
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        body = None
        if data is not None:
            body = json.dumps(data, ensure_ascii=False, allow_nan=False).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
        request = Request(self.url + path, body, headers)
        try:
            with build_opener(NoRedirect).open(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8-sig"))
        except HTTPError as exc:
            if exc.code in (401, 403):
                raise ClientError("Anmeldung abgelehnt oder abgelaufen. Bitte erneut verbinden.") from exc
            raise ClientError(f"Der Server meldet HTTP {exc.code}. Bitte Verbindung und Server prüfen.") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise ClientError("Server nicht erreichbar. Bitte Netzwerk und Server-Adresse prüfen.") from exc
        except (ValueError, UnicodeError) as exc:
            raise ClientError("Der Server hat keine gültige JSON-Antwort geliefert.") from exc

    def login(self, username: str, password: str) -> list[dict]:
        self.token = ""
        if not username.strip() or not password:
            raise ClientError("Bitte Benutzername und Passwort eingeben.")
        result = lower_keys(self.request("/api/login", {"Username": username.strip(), "Password": password}))
        token = result.get("token")
        if not isinstance(token, str) or not token.strip():
            raise ClientError("Der Server hat kein gültiges Anmeldetoken geliefert.")
        self.token = token
        try:
            events = records(self.request("/api/anlaesse"))
            for event in events:
                if type(event.get("id")) is not int or not isinstance(event.get("name"), str):
                    raise ClientError("Die Anlassliste ist unvollständig.")
            return events
        except Exception:
            self.token = ""
            raise


FIELDS = (
    "StartNr Primaerwertung Schussart BahnNr Sekundaerwertung Teiler Zeit Mouche X Y "
    "InTime TimeSinceChange SweepDirection Demonstration Match Stich InsDel TotalArt "
    "Gruppe Feuerart LogEvent LogTyp ZeitSeitJahresbeginn Abloesung Waffe Position TargetId ExterneNummer"
).split()
DECIMALS = {1, 4, 8, 9, 11}


def parse_shot(line: str) -> dict:
    try:
        fields = next(csv.reader([line], delimiter=";", strict=True))
        if len(fields) != 28:
            raise ValueError("28 Felder erwartet")
        shot = {}
        for i, (key, raw) in enumerate(zip(FIELDS, fields)):
            value = raw.strip()
            if i == 6:
                shot[key] = raw
            elif i in DECIMALS:
                value = value.replace(",", ".")
                if not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)", value):
                    raise ValueError("Ungültige Dezimalzahl")
                shot[key] = float(value)
                if not math.isfinite(shot[key]):
                    raise ValueError("Ungültige Dezimalzahl")
            else:
                value = "1" if i == 16 and value == "I" else value
                if not re.fullmatch(r"[+-]?\d+", value):
                    raise ValueError("Ungültige Ganzzahl")
                number = int(value)
                bits = 64 if i in (20, 22) else 32
                if not -(2 ** (bits - 1)) <= number < 2 ** (bits - 1):
                    raise ValueError("Zahl ausserhalb des gültigen Bereichs")
                shot[key] = number
        return shot
    except (ValueError, csv.Error, StopIteration) as exc:
        raise ClientError("Ungültige SIUS-Zeile: " + str(exc)) from exc


def source_date(mtime: float):
    """A suggestion only; operators can choose the shooting date explicitly."""
    return datetime.fromtimestamp(mtime).replace(hour=0, minute=0, second=0, microsecond=0)


def anchor_shot_time(shot: dict, reference: datetime):
    """Turn time-only SIUS values into a stable timestamp before journalling.

    The supplied SIUS fixture proves ZeitSeitJahresbeginn is centiseconds.
    Check its clock against Zeit to avoid silently assuming different units.
    """
    value = shot["Zeit"].strip()
    if not re.fullmatch(r"\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?", value):
        return shot
    try:
        clock = datetime.strptime(value, "%H:%M:%S.%f" if "." in value else "%H:%M:%S")
        counter = shot["ZeitSeitJahresbeginn"]
        if counter:
            stamp = datetime(reference.year, 1, 1) + timedelta(milliseconds=counter * 10)
            if stamp.year != reference.year or stamp.strftime("%H:%M:%S") != clock.strftime("%H:%M:%S"):
                raise ValueError("SIUS-Jahreszeit und Uhrzeit passen nicht zusammen")
        else:
            stamp = reference.replace(hour=clock.hour, minute=clock.minute, second=clock.second, microsecond=clock.microsecond)
        return {**shot, "Zeit": stamp.isoformat(sep=" ", timespec="milliseconds")}
    except (ValueError, OverflowError) as exc:
        raise ClientError("Schusszeit nicht eindeutig: " + str(exc)) from exc


def shooter_rows(shooters: list[dict]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\r\n")
    for shooter in shooters:
        first = str(shooter.get("vorname") or "").strip()
        last = str(shooter.get("name") or "").strip()
        # Existing server contract: standblatt ID goes into the first SIUS field.
        writer.writerow([shooter["id"], last, first, f"{first[0]}. {last}" if first else last] + [""] * 7)
    try:
        return stream.getvalue().encode("latin-1")
    except UnicodeEncodeError as exc:
        raise ClientError("Ein Name enthält Zeichen, die SIUS (ISO-8859-1) nicht unterstützt. Export unverändert.") from exc


def atomic_write(path: Path, data: bytes, append=False):
    """Replace only after the entire new file is written; preserve original on error."""
    if append:
        data = path.read_bytes() + data
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        for attempt in range(4):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt == 3:
                    raise
                time.sleep(0.1 * (attempt + 1))
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def validate_paths(import_path: str, export_path: str) -> tuple[Path, Path]:
    if not import_path.strip() or not export_path.strip():
        raise ClientError("Bitte SIUS-Schussdatei und Speicherort für die Schützenliste wählen.")
    source, target = Path(import_path).resolve(), Path(export_path).resolve()
    if source == target or (source.exists() and target.exists() and os.path.samefile(source, target)):
        raise ClientError("Schussdatei und Schützenliste müssen verschiedene Dateien sein.")
    if source.is_dir() or not source.parent.is_dir():
        raise ClientError("Der Speicherort der SIUS-Schussdatei wurde nicht gefunden.")
    if not target.parent.is_dir() or target.is_dir():
        raise ClientError("Der Speicherort für die Schützenliste ist ungültig.")
    return source, target


class Transfer:
    def __init__(self, api: Api, event: dict, source: Path, target: Path, journal_path: Path | None = None, reference_date: datetime | None = None):
        self.api, self.event, self.source, self.target = api, event, source, target
        self.reference_date = reference_date
        self.position = 0
        self.signature = None
        self.seen: set[str] = set()
        self.shooters: dict[int, dict] = {}
        self.last_id = 0
        self.lock = threading.RLock()
        if journal_path is None:
            journal_path = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "SiusClientV2" / "uebertragung.sqlite3"
        self.journal = Journal(journal_path, api.url + "|" + str(event["id"]))
        self.last_scan = None
        self.last_server = None
        self.last_export = None
        self.last_full_scan = 0.0
        self.partial_bytes = 0

    @property
    def endpoint(self):
        return f"/api/anlaesse/{self.event['id']}"

    def snapshot(self):
        journal = self.journal.stats()
        with self.lock:
            recent = journal["recent"]
            return {**journal, "shooters": len(self.shooters), "highest": max((s.get("startnummer", s["id"]) for s in self.shooters.values()), default=0),
                    "last": recent[-1]["Zeit"] if recent else "–", "event": self.event["name"],
                    "scan_at": self.last_scan, "server_at": self.last_server, "export_at": self.last_export,
                    "partial_bytes": self.partial_bytes}

    def get_shooters(self, path):
        result = records(self.api.request(path))
        for item in result:
            if type(item.get("id")) is not int or item["id"] <= 0:
                raise ClientError("Die Schützenliste enthält eine ungültige ID.")
            if type(item.get("startnummer", item["id"])) is not int:
                raise ClientError("Die Schützenliste enthält eine ungültige Startnummer.")
        return {s["id"]: s for s in result}

    def prepare(self):
        shooters = self.get_shooters(self.endpoint + "/shooters")
        payload = b"0,DummyName,Dummy,D. DummyName,,,,,,,\r\n" + shooter_rows(list(shooters.values()))
        atomic_write(self.target, payload)
        with self.lock:
            self.shooters = shooters
            self.last_id = max(shooters, default=0)
            self.last_export = time.time()
        # Winklar's unique import hash makes a complete restart reconciliation safe.
        self.journal.replay()

    def poll_shooters(self):
        shooters = self.get_shooters(self.endpoint + f"/shooters/new?sinceId={self.last_id}")
        shooters = {key: value for key, value in shooters.items() if key > self.last_id}
        self.last_server = time.time()
        if not shooters:
            return
        atomic_write(self.target, shooter_rows(list(shooters.values())), append=True)
        with self.lock:
            self.shooters.update(shooters)
            self.last_id = max(shooters)
            self.last_export = time.time()

    def rescan(self):
        # Preserve acknowledgements. Re-reading must not duplicate server results.
        self.signature = None
        self.position = 0

    def scan_shots(self, stop: threading.Event | None = None):
        stat = self.source.stat()
        reference = self.reference_date or source_date(stat.st_mtime)
        self.partial_bytes = 0
        signature = (stat.st_size, stat.st_mtime_ns)
        if signature != self.signature or time.monotonic() - self.last_full_scan >= 30:
            self.position = 0
            self.signature = signature
            self.last_full_scan = time.monotonic()
        while self.position < stat.st_size and not (stop and stop.is_set()):
            start = self.position
            with self.source.open("rb") as stream:
                stream.seek(start)
                data = stream.read(min(65536, stat.st_size - start))
            lines = data.split(b"\n")[:-1][:500]
            if not lines:
                self.partial_bytes = len(data)
                if len(data) == 65536:
                    raise ClientError("Eine SIUS-Zeile überschreitet 64 KiB oder hat keinen Zeilenumbruch.")
                break
            position = start + sum(len(line) + 1 for line in lines)
            shots, invalid, pending = [], [], set()
            for raw in lines:
                line = raw.decode("latin-1").rstrip("\r")
                if not line.strip() or line in self.seen or line in pending:
                    continue
                pending.add(line)
                try:
                    shots.append(anchor_shot_time(parse_shot(line), reference))
                except ClientError:
                    invalid.append(line)
            if invalid:
                error_path = self.source.with_name(self.source.name + f".fehler-{start}-{position}.csv")
                atomic_write(error_path, ("\r\n".join(invalid) + "\r\n").encode("latin-1"))
            self.journal.stage(shots, invalid)
            self.seen.update(pending)
            self.position = position
        self.last_scan = time.time()

    def poll_shots(self, stop: threading.Event | None = None):
        scan_error = None
        try:
            self.scan_shots(stop)
        except (OSError, ClientError) as exc:
            scan_error = exc
        while not (stop and stop.is_set()):
            batch = self.journal.pending()
            if not batch:
                break
            shots = [json.loads(payload) for _, payload in batch]
            result = self.api.request(self.endpoint + "/shots/import", {"AnlassId": self.event["id"], "Shots": shots})
            # Winklar commits all rows in one transaction. 'imported' counts
            # only NEW rows; the remainder already exists by unique import hash.
            if (not isinstance(result, dict) or result.get("success") is not True
                    or type(result.get("imported")) is not int or not 0 <= result["imported"] <= len(shots)):
                raise ClientError("Keine gültige Serverbestätigung. Der Block bleibt dauerhaft für einen erneuten Versuch vorgemerkt.")
            if "accepted" in result and (type(result["accepted"]) is not int or result["accepted"] != len(shots)):
                raise ClientError("Der Server hat nicht alle Schüsse angenommen. Die Übertragung wird wiederholt.")
            self.journal.acknowledge([key for key, _ in batch])
            self.last_server = time.time()
        if scan_error:
            raise scan_error
