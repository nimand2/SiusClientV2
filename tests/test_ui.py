import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import time
from pathlib import Path
import unittest

from PyQt6.QtWidgets import QApplication
from sius_client.ui import Window, STYLE
from sius_client.core import Transfer
from test_transfer import FakeApi, line


class UiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyleSheet(STYLE)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        source = root / "shots.csv"
        source.write_text(line() + "\n", encoding="latin-1")
        self.api = FakeApi()
        self.transfer = Transfer(self.api, {"id": 1, "name": "Testanlass"}, source, root / "Shooters.csv", root / "state.sqlite3")
        self.window = Window(persist=False)
        self.window.api = self.api
        self.window.transfer = self.transfer

    def tearDown(self):
        if self.window.live:
            self.window.pause_live()
            self.wait_until(lambda: self.window.live is None)
        self.window.close()
        self.app.processEvents()
        self.temp.cleanup()

    def wait_until(self, condition):
        deadline = time.monotonic() + 5
        while not condition() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        self.assertTrue(condition())

    def test_live_pause_and_health(self):
        self.transfer.prepare()
        self.window.begin_polling()
        self.wait_until(lambda: self.window.metrics["shots"].text() == "1")
        self.assertFalse(self.window.source.isEnabled())
        self.assertTrue(self.window.pause_button.isEnabled())
        self.assertIn("Überwachung läuft", self.window.health.text())
        self.assertEqual(self.window.table.rowCount(), 1)
        self.window.pause_live()
        self.wait_until(lambda: self.window.live is None)
        self.assertTrue(self.window.source.isEnabled())
        self.assertIn("Pausiert", self.window.badge.text())

    def test_error_visible_and_queue_preserved(self):
        self.api.fail = True
        self.window.begin_polling()
        self.wait_until(lambda: "Schussimport" in self.window.errors)
        self.assertEqual(self.window.metrics["queued"].text(), "1")
        self.assertIn("offline", self.window.error_label.text())
        self.assertIn("Störung", self.window.badge.text())

    def test_replay_updates_pending_indicator(self):
        self.transfer.poll_shots()
        self.window.render(self.transfer.snapshot())
        self.window.rescan()
        self.assertEqual(self.window.metrics["queued"].text(), "1")
        self.assertEqual(self.window.metrics["shots"].text(), "0")

    def test_settings_never_store_credentials(self):
        self.window.persist = True
        self.window.config = Path(self.temp.name) / "settings.json"
        self.window.password.setText("secret-not-to-store")
        self.window.save_settings()
        self.assertNotIn("secret-not-to-store", self.window.config.read_text())


if __name__ == "__main__":
    unittest.main()
