# SIUS Client V2

Python-Desktop-Anwendung für LGS Wangen. Die dunkle Oberfläche mit violetten Bedienelementen orientiert sich an der Schützennummeranzeige. Die bestehende C#-Anwendung und die Finalanzeige werden nicht verändert.

## Starten

**`Starten.cmd` doppelklicken.** Alternativ `dist/SiusClientV2.exe` starten. Die EXE enthält Python und PyQt6; auf dem Zielrechner ist keine Python-Installation nötig.

Falls die Windows-Anwendungssteuerung die unsignierte EXE blockiert, kann die eingerichtete Python-Anwendung mit **`Starten-Python.cmd`** gestartet werden. Dabei wird die vorhandene `.venv` benötigt; es wird keine Windows-Schutzfunktion verändert. Beim abschliessenden Live-Test am 11.10.2026 wurde die neu gebaute EXE durch diese Richtlinie blockiert, während die Anwendung und der Serverzugriff über die Python-Umgebung geprüft wurden.

1. Server-Adresse, Benutzername und Passwort eingeben und **Verbinden** wählen.
2. SIUS-Schussdatei und Speicherort für `Shooters.csv` wählen. Das müssen verschiedene Dateien sein. **Schiesstag prüfen**: Er wird aus dem Änderungsdatum der Datei vorgeschlagen und kann korrigiert werden. Der Dateiname ist frei wählbar.
3. Den richtigen Anlass wählen und **Live starten** drücken. Eine vorhandene Schützenliste wird nach Bestätigung ersetzt.
4. Zum Unterbrechen **Pausieren** verwenden. Zum Wiederabgleich pausieren, **Alles erneut abgleichen**, dann **Live starten** wählen.

Server-Adresse, Benutzername, Schiesstag und letzter Anlass werden gespeichert. Die beiden Dateipfade bleiben beim Programmstart leer und müssen neu gewählt werden. Passwort und API-Token werden nicht gespeichert. Nach einem Programmneustart deshalb erneut anmelden, Dateien wählen und Live starten.

## Woran erkenne ich, dass es läuft?

- **Live aktiv:** Überwachung eingeschaltet; aktuelle Serverprüfung erfolgreich.
- **Alles übertragen / Warte auf neue Schüsse:** Es liegen keine offenen vollständigen Datensätze vor. Ein unveränderter Schusszähler ist dabei normal.
- **Schüsse ausstehend:** Dauerhaft gespeicherte Datensätze, die noch bestätigt werden müssen.
- **Schüsse bestätigt:** Vom Server angenommene oder dort bereits vorhandene Datensätze. Bei einem vollständigen Wiederabgleich werden sie zunächst erneut als ausstehend gezählt.
- **Datei geprüft / Server erreicht:** Alter der jeweils letzten erfolgreichen Prüfung. Die Uhr aktualisiert sich jede Sekunde.
- **Letzte Schussbestätigung:** Wann ein Schussblock zuletzt erfolgreich abgeglichen wurde.
- **Live · Störung:** Fehlermeldung beachten. Netzwerkfehler werden automatisch mit wachsendem Abstand bis maximal 30 Sekunden erneut versucht. Bei abgelaufener Anmeldung pausieren und erneut verbinden.
- Eine unvollständige letzte CSV-Zeile wird erst nach dem abschliessenden Zeilenumbruch gesendet. Dieser Wartezustand wird angezeigt.

Ein Programmneustart ist bei normalen Netzwerkunterbrüchen nicht nötig. Das Protokoll nennt Änderungen und die Wiederherstellung der Verbindung. Ein zweiter V2-Start unter demselben Windows-Benutzer wird blockiert.

## Verhalten bei Unterbruch und Neustart

Schüsse werden **vor dem Versand** in einer lokalen SQLite-Warteschlange gesichert. Erst nach einer gültigen Serverantwort erfolgt die Bestätigung. Bei fehlender Antwort bleibt der Block ausstehend, auch wenn der Server ihn möglicherweise schon gespeichert hat. Wiederholungen werden vom Winklar-Server dedupliziert.

Nach einem neuen Programmstart und Live-Start werden auch bereits bestätigte, lokal gespeicherte Schüsse des Anlasses nochmals abgeglichen. Dadurch lassen sich z.B. nach einer Serverwiederherstellung fehlende Datensätze nachliefern. Ein blosses Pausieren/Fortsetzen beginnt dagegen keinen vollständigen Wiederabgleich. Nicht mehr in der Quelldatei vorhandene Schüsse bleiben in der Warteschlange erhalten. Fehlt die Quelldatei vorübergehend, werden gespeicherte offene Schüsse trotzdem gesendet und der Dateifehler angezeigt.

Die Quelle wird bei Änderung und spätestens alle 30 Sekunden vollständig neu geprüft. Ein bereits eingelesener identischer Datensatz wird lokal nicht nochmals angelegt. Ungültige Zeilen bleiben im Journal und zusätzlich in `.fehler-…csv` neben der Quelle erhalten. Sie müssen in der Quelle korrigiert werden; sie gelten nicht als erfolgreich übertragene Schüsse.

Vor dem Senden wird der zum Prüfzeitpunkt vorhandene Dateirückstand eingelesen. Offene Datensätze werden nach `ZeitSeitJahresbeginn`, danach numerisch nach `LogEvent` gesendet, in Blöcken von höchstens 500. Match- und Stichzähler werden nicht als zeitliche Reihenfolge verwendet. Später eintreffende ältere Schüsse benötigen zusätzlich die mitgelieferte Serverkorrektur für die richtige Serienzuordnung.

SIUS-Uhrzeiten ohne Datum werden vor dem Speichern eindeutig ergänzt: Der Jahreszeitzähler enthält Hundertstelsekunden seit Jahresbeginn. Das Jahr stammt aus dem gewählten **Schiesstag**, niemals aus dem Dateinamen. Der errechnete Zeitwert muss zur SIUS-Uhrzeit passen. Bei einem fehlenden/Null-Jahreszeitzähler wird das ganze eingestellte Datum verwendet. Bei historischen Dateien den vorgeschlagenen Schiesstag prüfen. Vollständige Zeitstempel werden unverändert übernommen.

## Voraussetzung auf dem Server

Die Anwendung richtet sich konkret an **[nimand2/winklar](https://github.com/nimand2/winklar)**, geprüft anhand des Ausgangsstands `1e2d5d8`.

Dieser Server importiert einen Block innerhalb einer Datenbanktransaktion und erkennt vorhandene Datensätze anhand des eindeutigen Index `uq_schussdaten_anlass_import_hash (id_anlass, import_hash)`. `imported` zählt ausschliesslich **neu eingefügte** Zeilen. Daher kann `success: true, imported: 0` einen vollständig erfolgreichen Wiederabgleich bedeuten. V2 akzeptiert dies korrekt. Falls der Server zusätzlich `accepted` liefert, muss diese Zahl exakt dem gesendeten Block entsprechen.

**V2 nicht mit einer älteren oder anderen Serverversion ohne diesen Duplikatschutz betreiben.** Eine laufende V1 sollte während des V2-Betriebs beendet sein. Der lokale Startschutz kann andere Rechner oder V1 nicht sperren.

Die vorbereiteten Serverdateien und eine Einspielanleitung liegen in **`server-update/`**. Sie korrigieren die Reihenfolge bei der Auswertung und ergänzen die ausdrückliche Bestätigung bereits vorhandener Schüsse. Sie sind lokal vorbereitet und wurden nicht auf GitHub oder einen produktiven Server hochgeladen.

## Lokale Daten

Unter `%LOCALAPPDATA%\SiusClientV2\`:

- `einstellungen.json`: Einstellungen ohne Passwort/Token.
- `uebertragung.sqlite3`: dauerhaftes Schussjournal, getrennt nach Server-Adresse und Anlass-ID.
- `uebertragung.sqlite3-wal` / `-shm`: SQLite-Begleitdateien während des Betriebs.
- `client.lock`: Schutz vor parallelem V2-Start.

Das Journal liegt bewusst ausserhalb von OneDrive. Nicht löschen, solange offene Schüsse vorhanden sind. Sicherung am besten nach dem Beenden des Clients erstellen. Für Tests wird eine separate temporäre Datenbank verwendet.

## Entwicklung und EXE erstellen

Python 3.12 oder neuer unter Windows:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe main.py
.\build.ps1
```

`build.ps1` führt die Python-Tests aus und erstellt danach `dist/SiusClientV2.exe`. Tests ohne Build:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Geprüft und noch offen

Automatisierte Tests decken Neustart, verlorene Antworten, Wiederabgleich, Reihenfolge über mehrere Blöcke, unvollständige Zeilen, CSV-Format, Dateiaustausch, Schreibfehler, Anlass-Trennung sowie Live-Anzeige/Pausieren ab. Die Server-Tests prüfen insbesondere verspätete Schüsse und die Übereinstimmung von Rangliste und Standblatt.

Die bereitgestellte echte Datei **`20251012.csv`** wurde lokal gegen einen simulierten Server getestet: **1'480 Zeilen, 1'480 bestätigte Datensätze, 0 ungültige Zeilen, 0 offene Datensätze, 0 zusätzliche Duplikate nach Neustart und Wiederabgleich**. Verlorene Antwort nach Speicherung und die chronologische Reihenfolge wurden mitgeprüft. Der Zeitbereich ist korrekt auf **12.10.2025, 09:15:32.190 bis 15:46:56.370** bezogen. Die Originaldatei wurde nur gelesen.

Am 11.10.2026 wurde zusätzlich der echte Server `winklarweb.emitprod.com` mit Anlass 9 «Chilbischiessen 2026» getestet. Aus `D:/LGS Wangen/fin/20261011.csv` wurden nach Benutzerfreigabe 1'234 Datensätze übertragen; 15 Zeilen mit Startnummer 16 wurden für diesen Test ausgeschlossen. Der Server bestätigte 826 neu eingefügte und 408 bereits vorhandene Datensätze. Nach erneuter Anmeldung und neu aufgebauter Übertragung wurden alle 1'234 erneut bestätigt und **0 weitere Datensätze eingefügt**. Die 61 Schützen wurden nach `C:/Users/troge/Downloads/Shooters.csv` exportiert; die vorherige Datei wurde im Testordner gesichert. Die Original-Schussdatei blieb unverändert; die Ausnahme für Nummer 16 gilt nur für diesen Test und ist kein allgemeiner Importfilter.

Der vorgeschaltete Zugriffsschutz lehnte Pythons Standardkennung ab. API-Anfragen identifizieren sich deshalb jetzt ausdrücklich mit `SiusClientV2/2.0 (Windows)`. HTTP 403 wird als Zugriffsproblem und HTTP 401 als Anmeldeproblem angezeigt. Die aktualisierte EXE enthält diese Korrektur; 32 Python-Tests bestehen.

Die Tests verwenden gespeicherte SIUS-Dateien; ein länger laufender Betrieb an der aktiven Anlage wurde noch nicht durchgeführt. Falls V1 historische Daten bereits mit einem falschen Importdatum auf dem Server angelegt hat, korrigiert der Wiederabgleich solche alten Datensätze nicht automatisch; diese müssen auf dem Server geprüft werden.
