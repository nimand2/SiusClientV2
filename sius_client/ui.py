from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import threading
import time

from PyQt6.QtCore import Qt, QThread, QTimer, QLockFile, QDate, pyqtSignal
from PyQt6.QtGui import QFontDatabase
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QDateEdit, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton,
    QScrollArea, QTableWidget, QTableWidgetItem, QHeaderView, QVBoxLayout, QWidget,
)

from .core import Api, ClientError, Transfer, atomic_write, validate_paths


STYLE = """
QWidget { background: #2f3030; color: #f4f3f8; font-family: 'Segoe UI'; font-size: 14px; }
QFrame#card { background: #363737; border: 1px solid #48494c; border-radius: 12px; }
QFrame#card QLabel, QFrame#card QWidget { background: transparent; }
QLabel#title { font-size: 29px; font-weight: 700; }
QLabel#subtitle, QLabel#muted { color: #bbbcc7; }
QLabel#section { font-size: 17px; font-weight: 600; }
QLabel#badge { background: #383666; color: #dddafa; border-radius: 12px; padding: 7px 14px; }
QLabel#metric { font-size: 30px; font-weight: 700; color: #b9b1ff; }
QLineEdit, QComboBox, QDateEdit { background: #292a2c; border: 1px solid #5c5a74; border-radius: 7px; padding: 9px 12px; min-height: 20px; selection-background-color: #6357a6; }
QLineEdit:focus, QComboBox:focus { border: 1px solid #b1a4ff; }
QLineEdit:disabled, QComboBox:disabled { color: #a2a1ab; background: #303133; }
QComboBox QAbstractItemView { background: #383666; color: white; selection-background-color: #6357a6; }
QPushButton { background: #383666; border: 1px solid #57527f; border-radius: 8px; padding: 10px 16px; font-weight: 600; min-height: 20px; }
QPushButton:hover { background: #4b467f; border-color: #a99de8; }
QPushButton:pressed { background: #302d56; }
QPushButton:focus { border: 2px solid #b1a4ff; }
QPushButton:disabled { color: #898895; background: #33333e; border-color: #45454d; }
QPushButton#primary { background: #7565c4; border-color: #9686e0; color: white; }
QPushButton#primary:hover { background: #8675d5; }
QPushButton#primary:disabled { background: #454151; border-color: #55515f; color: #96919f; }
QTableWidget { background: #303132; alternate-background-color: #363739; border: 0; gridline-color: #45454d; selection-background-color: #4b467f; }
QHeaderView::section { background: #383666; color: #dddafa; border: 0; padding: 10px; font-weight: 600; }
QPlainTextEdit { background: #292a2c; border: 1px solid #48494c; border-radius: 8px; padding: 8px; font-size: 12px; }
QScrollArea { border: none; }
QToolTip { background: #383666; color: white; border: 1px solid #a99de8; }
"""


class Job(QThread):
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, function, parent=None):
        super().__init__(parent)
        self.function = function

    def run(self):
        try:
            self.succeeded.emit(self.function())
        except Exception as exc:
            self.failed.emit(str(exc))


class Live(QThread):
    updated = pyqtSignal(object)
    status = pyqtSignal(str, str)

    def __init__(self, transfer, parent=None):
        super().__init__(parent)
        self.transfer = transfer
        self.stop = threading.Event()

    def loop(self, name, action, interval):
        previous = None
        failures = 0
        while not self.stop.is_set():
            error = ""
            try:
                action()
                failures = 0
            except Exception as exc:
                error = str(exc)
                failures += 1
            self.updated.emit(self.transfer.snapshot())
            if error != previous:
                self.status.emit(name, error)
                previous = error
            self.stop.wait(min(30, interval * (2 ** min(failures, 5))))

    def run(self):
        shots = threading.Thread(target=self.loop, args=("Schussimport", lambda: self.transfer.poll_shots(self.stop), 1))
        shooters = threading.Thread(target=self.loop, args=("Schützenexport", self.transfer.poll_shooters, 3))
        shots.start()
        shooters.start()
        shots.join()
        shooters.join()


def label(text, kind=None):
    widget = QLabel(text)
    if kind:
        widget.setObjectName(kind)
    widget.setWordWrap(True)
    return widget


def button(text, action, primary=False):
    widget = QPushButton(text)
    if primary:
        widget.setObjectName("primary")
    widget.clicked.connect(action)
    return widget


def card(title):
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(20, 16, 20, 18)
    layout.setSpacing(12)
    layout.addWidget(label(title, "section"))
    return frame, layout


class Window(QMainWindow):
    def __init__(self, persist=True):
        super().__init__()
        self.setWindowTitle("SIUS Client V2 · Wettkampfbetrieb")
        self.resize(1180, 920)
        self.setMinimumSize(900, 650)
        self.api = None
        self.transfer = None
        self.job = None
        self.live = None
        self.errors = {}
        self.closing = False
        self.persist = persist
        self.busy = False
        self.saved_event_id = None
        self._recent = None
        self.last_state = {}
        self.config = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "SiusClientV2" / "einstellungen.json"
        self.build_ui()
        if persist:
            self.load_settings()
        self.update_controls()
        self.heartbeat = QTimer(self)
        self.heartbeat.timeout.connect(self.refresh_health)
        self.heartbeat.start(1000)

    def build_ui(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        root = QWidget()
        page = QVBoxLayout(root)
        page.setContentsMargins(28, 24, 28, 20)
        page.setSpacing(16)
        scroll.setWidget(root)
        self.setCentralWidget(scroll)

        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.addWidget(label("SIUS Client", "title"))
        titles.addWidget(label("Schützen bereitstellen. Schüsse übertragen. Wettkampf im Blick.", "subtitle"))
        header.addLayout(titles, 1)
        self.badge = label("●  Nicht verbunden", "badge")
        header.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignTop)
        header.addWidget(label("V2 · Python", "muted"), 0, Qt.AlignmentFlag.AlignTop)
        page.addLayout(header)

        row = QHBoxLayout()
        connection, layout = card("01  Verbindung zur Wettkampfverwaltung")
        fields = QGridLayout()
        self.server = QLineEdit()
        self.server.setPlaceholderText("https://dein-wettkampf-server.ch")
        self.username = QLineEdit()
        self.username.setPlaceholderText("Benutzername")
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText("Passwort")
        for i, (text, field) in enumerate((("Server-Adresse", self.server), ("Benutzername", self.username), ("Passwort", self.password))):
            name = label(text)
            name.setBuddy(field)
            fields.addWidget(name, i, 0)
            fields.addWidget(field, i, 1)
        layout.addLayout(fields)
        self.connect_button = button("Verbinden", self.connect_server)
        layout.addWidget(self.connect_button)
        row.addWidget(connection, 1)

        files, layout = card("02  SIUS-Dateien wählen")
        self.source = QLineEdit()
        self.source.setPlaceholderText("Schussdatei von SIUS (.csv)")
        self.target = QLineEdit()
        self.target.setPlaceholderText("Schützenliste für SIUS · Shooters.csv")
        self.source_button = button("Datei wählen …", self.choose_source)
        self.target_button = button("Speicherort …", self.choose_target)
        for text, field, action in (("Schüsse einlesen · SIUS → Server", self.source, self.source_button), ("Schützen exportieren · Server → SIUS", self.target, self.target_button)):
            layout.addWidget(label(text, "muted"))
            file_row = QHBoxLayout()
            file_row.addWidget(field, 1)
            file_row.addWidget(action)
            layout.addLayout(file_row)
        layout.addWidget(label("Die Schützenliste wird beim Start für den gewählten Anlass neu erstellt.", "muted"))
        date_row = QHBoxLayout()
        date_row.addWidget(label("Schiesstag", "muted"))
        self.shooting_date = QDateEdit(QDate.currentDate())
        self.shooting_date.setDisplayFormat("dd.MM.yyyy")
        self.shooting_date.setCalendarPopup(True)
        self.shooting_date.setToolTip("Jahr für den SIUS-Jahreszeitzähler. Bei fehlendem Jahreszeitzähler wird das ganze Datum verwendet. Der Dateiname ist frei wählbar.")
        date_row.addWidget(self.shooting_date)
        layout.addLayout(date_row)
        row.addWidget(files, 1)
        page.addLayout(row)

        event, layout = card("03  Anlass und Live-Betrieb")
        actions = QHBoxLayout()
        self.events = QComboBox()
        self.events.addItem("Zuerst mit dem Server verbinden", None)
        self.events.setMinimumWidth(220)
        self.events.currentIndexChanged.connect(self.update_controls)
        actions.addWidget(self.events, 1)
        self.start_button = button("Live starten", self.start_live, True)
        self.pause_button = button("Pausieren", self.pause_live)
        self.rescan_button = button("Alles erneut abgleichen", self.rescan)
        self.rescan_button.setToolTip("Sendet auch bereits bestätigte Schüsse erneut. Winklar erkennt vorhandene Schüsse anhand ihres Import-Hashs.")
        for item in (self.start_button, self.pause_button, self.rescan_button):
            actions.addWidget(item)
        layout.addLayout(actions)
        self.state_label = label("Bereit. Verbinde dich mit dem Server und wähle die SIUS-Dateien.", "muted")
        layout.addWidget(self.state_label)
        self.error_label = label("")
        self.error_label.setStyleSheet("color: #ffd093;")
        self.error_label.hide()
        layout.addWidget(self.error_label)
        self.health = label("Überwachung noch nicht gestartet.", "muted")
        layout.addWidget(self.health)
        page.addWidget(event)

        metrics = QHBoxLayout()
        self.metrics = {}
        for key, title in (("shooters", "Schützen exportiert"), ("queued", "Schüsse ausstehend"), ("shots", "Schüsse bestätigt"), ("last", "Letzter Schuss")):
            frame, box = card(title)
            value = label("–" if key == "last" else "0", "metric")
            box.addWidget(value)
            self.metrics[key] = value
            metrics.addWidget(frame, 1)
        page.addLayout(metrics)

        shots, layout = card("Zuletzt übertragene Schüsse")
        self.empty = label("Noch keine Schüsse übertragen. Bestätigte Schüsse erscheinen hier automatisch.", "muted")
        layout.addWidget(self.empty)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Startnummer", "Bahn", "Zeit", "Schussart", "Wertung", "LogEvent"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setMinimumHeight(150)
        self.table.setMaximumHeight(220)
        layout.addWidget(self.table)
        page.addWidget(shots)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(300)
        self.log.setFixedHeight(88)
        self.log.setPlaceholderText("Betriebsmeldungen erscheinen hier.")
        page.addWidget(self.log)
        page.addWidget(label("SIUS Client V2  ·  LGS Wangen  ·  Schussprüfung jede Sekunde, neue Schützen alle 3 Sekunden", "muted"))
        for field in (self.server, self.username, self.password, self.source, self.target):
            field.setMinimumWidth(100)
        self.password.returnPressed.connect(self.connect_server)

    def message(self, text):
        self.log.appendPlainText(datetime.now().strftime("%H:%M:%S") + "  ·  " + text)

    def load_settings(self):
        try:
            data = json.loads(self.config.read_text(encoding="utf-8"))
            self.saved_event_id = data.get("event_id")
            saved_date = QDate.fromString(str(data.get("shooting_date", "")), "yyyy-MM-dd")
            if saved_date.isValid():
                self.shooting_date.setDate(saved_date)
            for key, field in self.settings_fields().items():
                field.setText(str(data.get(key, "")))
        except FileNotFoundError:
            pass
        except (ValueError, OSError, AttributeError):
            self.message("Gespeicherte Einstellungen konnten nicht geladen werden.")

    def settings_fields(self):
        return {"server": self.server, "username": self.username, "source": self.source, "target": self.target}

    def save_settings(self):
        if not self.persist:
            return
        try:
            self.config.parent.mkdir(parents=True, exist_ok=True)
            data = {key: field.text() for key, field in self.settings_fields().items()}
            selected = self.events.currentData()
            if selected:
                self.saved_event_id = selected["id"]
            data["event_id"] = self.saved_event_id
            data["shooting_date"] = self.shooting_date.date().toString("yyyy-MM-dd")
            atomic_write(self.config, json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))
        except OSError:
            self.message("Einstellungen konnten nicht gespeichert werden.")

    def choose_source(self):
        path, _ = QFileDialog.getOpenFileName(self, "SIUS-Schussdatei wählen", self.source.text(), "CSV-Dateien (*.csv);;Alle Dateien (*)")
        if path:
            self.source.setText(path)
            modified = datetime.fromtimestamp(Path(path).stat().st_mtime)
            self.shooting_date.setDate(QDate(modified.year, modified.month, modified.day))

    def choose_target(self):
        path, _ = QFileDialog.getSaveFileName(self, "Schützenliste für SIUS speichern", self.target.text() or "Shooters.csv", "CSV-Dateien (*.csv)")
        if path:
            self.target.setText(path)

    def fail(self, text):
        self.state_label.setText("Aktion fehlgeschlagen. Bitte die Meldung prüfen.")
        self.message(text)
        self.error_label.setText(text)
        self.error_label.show()

    def run_job(self, function, success):
        self.busy = True
        self.update_controls()
        self.job = Job(function, self)
        self.job.succeeded.connect(success)
        self.job.failed.connect(self.fail)
        self.job.finished.connect(self.job_finished)
        self.job.start()

    def job_finished(self):
        job = self.job
        self.job = None
        self.busy = False
        job.deleteLater()
        self.update_controls()
        if self.closing:
            self.close()

    def connect_server(self):
        if self.busy or self.live:
            return
        try:
            api = Api(self.server.text())
            username, password = self.username.text(), self.password.text()
            if not username.strip() or not password:
                raise ClientError("Bitte Benutzername und Passwort eingeben.")
        except ClientError as exc:
            self.fail(str(exc))
            return
        self.api = None
        self.events.clear()
        self.events.addItem("Verbindung wird hergestellt …", None)
        self.badge.setText("●  Verbindung wird hergestellt")
        self.state_label.setText("Anmelden und Anlässe laden …")
        self.error_label.hide()
        self.save_settings()

        def connected(events):
            self.api = api
            self.password.clear()
            self.events.clear()
            self.events.addItem("Bitte Anlass wählen", None)
            for event in events:
                self.events.addItem(event["name"], event)
                if event["id"] == self.saved_event_id:
                    self.events.setCurrentIndex(self.events.count() - 1)
            if not events:
                self.events.addItem("Keine Anlässe vorhanden", None)
            self.badge.setText("●  Verbunden")
            self.state_label.setText("Anlass wählen und Live-Betrieb starten." if events else "Auf diesem Server sind keine Anlässe vorhanden.")
            self.message(f"Verbindung hergestellt · {len(events)} Anlässe geladen.")
        self.run_job(lambda: api.login(username, password), connected)

    def start_live(self):
        if self.busy or self.live or not self.api:
            return
        try:
            event = self.events.currentData()
            if not event:
                raise ClientError("Bitte einen Anlass auswählen.")
            source, target = validate_paths(self.source.text(), self.target.text())
            if self.server.text().strip().rstrip("/") != self.api.url:
                raise ClientError("Die Server-Adresse wurde geändert. Bitte zuerst erneut verbinden.")
        except (ClientError, OSError) as exc:
            self.fail(str(exc))
            return
        old = self.transfer
        reference_date = datetime.combine(self.shooting_date.date().toPyDate(), datetime.min.time())
        same = old and old.api.url == self.api.url and old.event["id"] == event["id"] and old.source == source and old.target == target and old.reference_date == reference_date
        if same:
            old.api = self.api
            self.begin_polling()
            return
        if old:
            answer = QMessageBox.question(self, "Neue Übertragung starten?", "Du wechselst den Anlass oder die Dateien. Die Schussdatei wird dem jetzt gewählten Anlass zugeordnet. Fortfahren?")
            if answer != QMessageBox.StandardButton.Yes:
                return
        if target.exists():
            answer = QMessageBox.question(self, "Schützenliste neu erstellen?", f"Die vorhandene Datei wird durch die Schützenliste dieses Anlasses ersetzt:\n{target}\n\nFortfahren?")
            if answer != QMessageBox.StandardButton.Yes:
                return
        transfer = Transfer(self.api, event, source, target, reference_date=reference_date)
        self.save_settings()
        self.state_label.setText("Schützen laden und SIUS-Liste erstellen …")
        self.error_label.hide()

        def prepared(_):
            self.transfer = transfer
            self.errors.clear()
            self.render(transfer.snapshot())
            if not self.closing:
                self.begin_polling()
        self.run_job(transfer.prepare, prepared)

    def begin_polling(self):
        self.errors.clear()
        self.error_label.hide()
        self.live = Live(self.transfer, self)
        self.live.updated.connect(self.render)
        self.live.status.connect(self.live_status)
        self.live.finished.connect(self.live_finished)
        self.live.start()
        self.badge.setText("●  Live aktiv")
        self.state_label.setText("Live aktiv · " + self.transfer.event["name"])
        self.message("Live-Betrieb gestartet · " + self.transfer.event["name"])
        self.update_controls()

    def pause_live(self):
        if self.live:
            self.live.stop.set()
            self.pause_button.setEnabled(False)
            self.state_label.setText("Laufende Übertragungen abschliessen …")

    def live_finished(self):
        worker = self.live
        self.live = None
        worker.deleteLater()
        self.badge.setText("●  Pausiert")
        self.state_label.setText("Live-Betrieb pausiert · " + self.transfer.event["name"])
        self.message("Live-Betrieb pausiert. Bestätigte Schüsse bleiben in dieser Sitzung vorgemerkt.")
        self.update_controls()
        if self.closing:
            self.close()

    def live_status(self, area, error):
        previous = self.errors.pop(area, None)
        if error:
            self.errors[area] = error
            self.message(area + ": " + error)
        elif previous:
            self.message(area + ": Verbindung wiederhergestellt.")
        self.badge.setText("●  Live · Störung" if self.errors else "●  Live aktiv")
        self.show_errors()

    def show_errors(self):
        lines = [f"{area}: {error}" for area, error in self.errors.items()]
        if self.last_state.get("invalid"):
            lines.append(f"{self.last_state['invalid']} ungültige Zeilen gesichert. Fehlerdateien liegen neben der SIUS-Schussdatei.")
        self.error_label.setText("\n".join(lines))
        self.error_label.setVisible(bool(lines))

    def rescan(self):
        if self.transfer and not self.live and not self.busy:
            self.transfer.rescan()
            self.transfer.journal.replay()
            self.render(self.transfer.snapshot())
            self.state_label.setText("Vollständiger Wiederabgleich vorbereitet. Jetzt Live starten.")
            self.message("Alle gespeicherten Schüsse werden erneut abgeglichen. Winklar überspringt vorhandene Datensätze.")

    def render(self, state):
        self.last_state = state
        for key, widget in self.metrics.items():
            widget.setText(str(state[key]))
        self.show_errors()
        self.refresh_health()
        recent = state["recent"]
        if recent == self._recent:
            return
        self._recent = recent
        self.empty.setVisible(not recent)
        self.table.setRowCount(len(recent))
        for row, shot in enumerate(reversed(recent)):
            values = [shot["StartNr"], shot["BahnNr"], shot["Zeit"], {0: "Probe", 1: "Match", 8: "Final"}.get(shot["Schussart"], str(shot["Schussart"])), f"{shot['Primaerwertung']:.1f}", shot["LogEvent"]]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row, col, item)

    def refresh_health(self):
        def age(key):
            stamp = self.last_state.get(key)
            return f"vor {max(0, int(time.time() - stamp))} s" if stamp else "noch keine"
        active = self.live and not self.live.stop.is_set()
        prefix = "● Überwachung läuft" if active else "Überwachung pausiert"
        self.health.setText(f"{prefix} · {datetime.now():%H:%M:%S}  |  Datei geprüft: {age('scan_at')}  |  Server erreicht: {age('server_at')}\nLetzte Schussbestätigung: {age('confirmed_at')}  ·  {self.last_state.get('queued', 0)} Schüsse dauerhaft vorgemerkt")
        if active and not self.errors:
            stale = not self.last_state.get("server_at") or time.time() - self.last_state["server_at"] > 15
            self.badge.setText("●  Live · Antwort ausstehend" if stale else "●  Live aktiv")
            if not stale and self.last_state.get("queued", 0) == 0:
                message = "Warte auf Abschluss der letzten SIUS-Zeile" if self.last_state.get("partial_bytes") else "Alles übertragen · Warte auf neue Schüsse"
                self.state_label.setText(message + " · " + self.transfer.event["name"])

    def update_controls(self, *_):
        ready = not self.busy and not self.live and not self.closing
        for field in (self.server, self.username, self.password, self.source, self.target):
            field.setEnabled(ready)
        self.source_button.setEnabled(ready)
        self.target_button.setEnabled(ready)
        self.shooting_date.setEnabled(ready)
        self.connect_button.setEnabled(ready)
        self.connect_button.setText("Erneut verbinden" if self.api else "Verbinden")
        self.events.setEnabled(ready and self.api is not None)
        self.start_button.setEnabled(ready and self.api is not None and self.events.currentData() is not None)
        self.pause_button.setEnabled(self.live is not None and not self.live.stop.is_set() and not self.closing)
        self.rescan_button.setEnabled(ready and self.transfer is not None)
        if ready and not self.api:
            self.badge.setText("●  Nicht verbunden")

    def closeEvent(self, event):
        if self.live or self.job:
            self.closing = True
            self.pause_live()
            self.state_label.setText("Laufende Übertragungen abschliessen und Anwendung schliessen …")
            self.update_controls()
            event.ignore()
            return
        self.save_settings()
        event.accept()


def run():
    import sys
    app = QApplication(sys.argv)
    if os.environ.get("QT_QPA_PLATFORM") == "offscreen":
        for font in ("segoeui.ttf", "segoeuib.ttf"):
            QFontDatabase.addApplicationFont(str(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / font))
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    lock = None
    if "--screenshot" not in sys.argv:
        folder = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "SiusClientV2"
        folder.mkdir(parents=True, exist_ok=True)
        lock = QLockFile(str(folder / "client.lock"))
        lock.setStaleLockTime(0)
        if not lock.tryLock(0):
            QMessageBox.information(None, "SIUS Client läuft bereits", "SIUS Client V2 ist bereits geöffnet. Bitte das vorhandene Fenster verwenden.")
            return 0
    window = Window(persist="--screenshot" not in sys.argv)
    window.show()
    if "--screenshot" in sys.argv:
        window.resize(1180, 1050)
        path = sys.argv[sys.argv.index("--screenshot") + 1]
        def capture():
            window.grab().save(path)
            window.close()
        QTimer.singleShot(400, capture)
    return app.exec()
