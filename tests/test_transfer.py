import csv
from datetime import datetime
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from sius_client.core import Api, ClientError, Transfer, atomic_write, normalise_url, parse_shot, shooter_rows, validate_paths, anchor_shot_time, source_date


def line(event=1, stamp=None, **changes):
    values = ["3000", "10,4", "1", "2", "10", "12", "2026-10-11 10:30:00", "1", "0.12", "-0.3", "1", "2.5", "0", "0", "1", "1", "I", "0", "0", "0", str(event), "1", str(stamp if stamp is not None else event), "0", "1", "0", "2", "0"]
    for key, value in changes.items():
        values[int(key)] = str(value)
    return ";".join(values)


class FakeApi:
    url = "https://winklar.test"
    def __init__(self):
        self.saved = {}
        self.requests = []
        self.fail = False
        self.lose_response = False
        self.response = None
        self.shooters = [{"id": 3000, "startnummer": 3000, "name": "Müller", "vorname": "Anna"}]

    def request(self, path, data=None):
        if path.endswith("/shooters"):
            return self.shooters
        if "/shooters/new" in path:
            return self.shooters
        self.requests.append(data)
        if self.fail:
            raise ClientError("Test: offline")
        if self.response is not None:
            return self.response
        imported = 0
        for shot in data["Shots"]:
            key = json.dumps(shot, sort_keys=True)
            if key not in self.saved:
                self.saved[key] = shot
                imported += 1
        if self.lose_response:
            self.lose_response = False
            raise ClientError("Antwort nach Speichern verloren")
        return {"success": True, "imported": imported}


class TransferTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "shots.csv"
        self.target = self.root / "Shooters.csv"
        self.source.write_bytes(b"")
        self.api = FakeApi()
        self.transfer = self.new_transfer()

    def tearDown(self):
        self.temp.cleanup()

    def new_transfer(self, event=1):
        return Transfer(self.api, {"id": event, "name": "Testanlass"}, self.source, self.target, self.root / "journal.sqlite3")

    def write(self, *rows):
        self.source.write_bytes(("\r\n".join(rows) + "\r\n").encode("latin-1"))

    def test_parser_preserves_contract(self):
        shot = parse_shot(line())
        self.assertEqual(len(shot), 28)
        self.assertEqual(shot["Primaerwertung"], 10.4)
        self.assertEqual(shot["InsDel"], 1)
        self.assertEqual(shot["TimeSinceChange"], 2.5)

    def test_invalid_values_rejected(self):
        for value in ("NaN", "Inf", "1e2", "", "10.3.2"):
            with self.assertRaises(ClientError):
                parse_shot(line(**{"1": value}))
        with self.assertRaises(ClientError):
            parse_shot(line(**{"20": 2**64}))
        with self.assertRaises(ClientError):
            parse_shot(line() + ";extra")

    def test_quoted_decimal_and_time(self):
        shot = parse_shot(line(**{"1": '"10,4"', "6": '"10:30;01"'}))
        self.assertEqual(shot["Zeit"], "10:30;01")

    def test_unfinished_line_waits(self):
        self.source.write_bytes(line().encode("latin-1"))
        self.transfer.poll_shots()
        self.assertFalse(self.api.requests)
        with self.source.open("ab") as file:
            file.write(b"\n")
        self.transfer.poll_shots()
        self.assertEqual(self.transfer.snapshot()["shots"], 1)

    def test_retry_survives_restart_and_missing_source(self):
        self.write(line())
        self.api.fail = True
        with self.assertRaises(ClientError):
            self.transfer.poll_shots()
        self.assertEqual(self.transfer.snapshot()["queued"], 1)
        restarted = self.new_transfer()
        self.source.unlink()
        self.api.fail = False
        with self.assertRaises(FileNotFoundError):
            restarted.poll_shots()
        self.assertEqual(restarted.snapshot()["shots"], 1)
        self.assertEqual(restarted.snapshot()["queued"], 0)

    def test_lost_response_retries_without_duplicates(self):
        self.write(line())
        self.api.lose_response = True
        with self.assertRaises(ClientError):
            self.transfer.poll_shots()
        restarted = self.new_transfer()
        restarted.poll_shots()
        self.assertEqual(len(self.api.saved), 1)
        self.assertEqual(restarted.snapshot()["shots"], 1)
        self.assertEqual(len(self.api.requests), 2)

    def test_restart_reconciles_previously_confirmed_rows(self):
        self.write(line())
        self.transfer.poll_shots()
        self.api.saved.clear()  # e.g. restored server backup
        restarted = self.new_transfer()
        restarted.prepare()
        restarted.poll_shots()
        self.assertEqual(len(self.api.saved), 1)
        self.assertEqual(len(self.api.requests), 2)

    def test_sort_entire_backlog_before_batching(self):
        self.write(*(line(n) for n in range(1200, 0, -1)))
        self.transfer.poll_shots()
        order = [shot["LogEvent"] for batch in self.api.requests for shot in batch["Shots"]]
        self.assertEqual(order, list(range(1, 1201)))
        self.assertEqual([len(batch["Shots"]) for batch in self.api.requests], [500, 500, 200])

    def test_source_time_precedes_restarted_event_counter(self):
        self.write(line(1, 200), line(90, 100))
        self.transfer.poll_shots()
        self.assertEqual([s["LogEvent"] for s in self.api.requests[0]["Shots"]], [90, 1])

    def test_duplicate_logevent_different_shots_preserved(self):
        self.write(line(), line(**{"3": 3}), line())
        self.transfer.poll_shots()
        self.assertEqual(len(self.api.saved), 2)

    def test_file_replacement_equal_size_is_detected(self):
        self.write(line(1))
        self.transfer.poll_shots()
        stamp = self.source.stat().st_mtime_ns
        self.write(line(2))
        os.utime(self.source, ns=(stamp + 1000000000, stamp + 1000000000))
        self.transfer.poll_shots()
        self.assertEqual(len(self.api.saved), 2)

    def test_periodic_rescan_detects_unchanged_metadata(self):
        self.write(line(1))
        self.transfer.poll_shots()
        stamp = self.source.stat().st_mtime_ns
        self.write(line(2))
        os.utime(self.source, ns=(stamp, stamp))
        self.transfer.last_full_scan = 0
        self.transfer.poll_shots()
        self.assertEqual(len(self.api.saved), 2)

    def test_invalid_row_does_not_block_good_shots(self):
        self.write(line(), "invalid", line(2))
        self.transfer.poll_shots()
        self.assertEqual(self.transfer.snapshot()["invalid"], 1)
        self.assertEqual(self.transfer.snapshot()["shots"], 2)
        self.assertTrue(list(self.root.glob("shots.csv.fehler-*.csv")))
        self.new_transfer().poll_shots()
        self.assertEqual(self.transfer.snapshot()["invalid"], 1)

    def test_malformed_ack_does_not_commit(self):
        self.write(line())
        for response in ({"success": False}, {"success": True}, {"success": True, "imported": -1}, {"success": True, "imported": 2}, {"success": True, "imported": True}):
            self.api.response = response
            with self.assertRaises(ClientError):
                self.transfer.poll_shots()
            self.assertEqual(self.transfer.snapshot()["queued"], 1)

    def test_new_shooters_atomic_and_deduplicated(self):
        self.transfer.prepare()
        self.api.shooters += [{"id": 3001, "name": "Test, Name", "vorname": "Eva"}] * 2
        self.transfer.poll_shooters()
        self.transfer.poll_shooters()
        rows = list(csv.reader(io.StringIO(self.target.read_text(encoding="latin-1"))))
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(len(row) == 11 for row in rows))
        self.assertEqual(rows[-1][1], "Test, Name")

    def test_failed_export_preserves_file_and_cursor(self):
        self.transfer.prepare()
        original = self.target.read_bytes()
        self.api.shooters.append({"id": 3001, "name": "€", "vorname": "Eva"})
        with self.assertRaises(ClientError):
            self.transfer.poll_shooters()
        self.assertEqual(self.target.read_bytes(), original)
        self.assertEqual(self.transfer.last_id, 3000)

    def test_locked_replace_preserves_original(self):
        self.target.write_bytes(b"original")
        with patch("sius_client.core.os.replace", side_effect=PermissionError), patch("sius_client.core.time.sleep"):
            with self.assertRaises(PermissionError):
                atomic_write(self.target, b"new")
        self.assertEqual(self.target.read_bytes(), b"original")
        self.assertFalse(list(self.root.glob("*.tmp")))

    def test_scope_separates_events(self):
        self.write(line())
        self.transfer.poll_shots()
        other = self.new_transfer(2)
        self.assertEqual(other.snapshot()["shots"], 0)

    def test_explicit_partial_acceptance_is_not_committed(self):
        self.write(line())
        self.api.response = {"success": True, "imported": 0, "accepted": 0}
        with self.assertRaises(ClientError):
            self.transfer.poll_shots()
        self.assertEqual(self.transfer.snapshot()["queued"], 1)

    def test_real_sius_centiseconds_have_stable_date(self):
        shot = parse_shot(line(**{"6": "09:15:32.19", "22": "2457093219"}))
        reference = datetime(2025, 10, 12)
        self.assertEqual(anchor_shot_time(shot, reference)["Zeit"], "2025-10-12 09:15:32.190")

    def test_mismatched_time_counter_rejected(self):
        shot = parse_shot(line(**{"6": "10:15:32.19", "22": "2457093219"}))
        with self.assertRaises(ClientError):
            anchor_shot_time(shot, datetime(2025, 10, 12))

    def test_arbitrary_filename_and_explicit_year(self):
        self.source = self.root / "beliebiger-dateiname.csv"
        self.write(line(**{"6": "09:15:32.19", "22": "2457093219"}))
        transfer = self.new_transfer()
        transfer.reference_date = datetime(2025, 10, 12)
        transfer.poll_shots()
        self.assertEqual(self.api.requests[0]["Shots"][0]["Zeit"], "2025-10-12 09:15:32.190")

    def test_stop_keeps_queue(self):
        self.write(line())
        self.transfer.scan_shots()
        stop = threading.Event()
        stop.set()
        self.transfer.poll_shots(stop)
        self.assertEqual(self.transfer.snapshot()["queued"], 1)

    def test_paths_cannot_overwrite_shots(self):
        with self.assertRaises(ClientError):
            validate_paths(str(self.source), str(self.source))

    def test_url_validation(self):
        self.assertEqual(normalise_url(" https://example.ch/app/ "), "https://example.ch/app")
        for url in ("example.ch", "file:///tmp", "https://u:p@example.ch", "https://example.ch?secret=x", "https://example.ch:bad"):
            with self.assertRaises(ClientError):
                normalise_url(url)


if __name__ == "__main__":
    unittest.main()
