# Winklar-Anpassung für SIUS Client V2

Ausgangsstand: `nimand2/winklar`, Commit `1e2d5d8`.

## Enthaltene Korrekturen

- `app/Services/Schussreihenfolge.php`: gemeinsame zeitliche Reihenfolge nach Schussdatum/-zeit, SIUS-Jahreszeit, numerischem LogEvent und zuletzt Datenbank-ID.
- `app/Services/AbrechnungsService.php` und `RanglistenService.php`: verwenden diese Reihenfolge. Verspätet eingetroffene Schüsse werden somit in die passende Serie einsortiert. Match-/Stichzähler können weiterhin zwischen Serien neu beginnen.
- `app/Controllers/ClientApiController.php`: ergänzt `accepted` (alle angenommenen Zeilen) und `duplicates` (bereits vorhanden) zur bisherigen Antwort mit `imported` (neu eingefügt).
- Ergänzte Tests für verspätete Datensätze, numerische Ereignisnummern und identische Ergebnisse in Rangliste/Standblatt. Bestehende Tests bleiben enthalten.

## Einspielen

Die Dateien sind **nur vorbereitet**, nicht veröffentlicht. Vor dem Einspielen Dateien und Datenbank sichern. Bei inzwischen geändertem Servercode den Patch prüfen und zusammenführen, statt komplette Dateien blind zu ersetzen.

Im passenden Winklar-Git-Projekt:

```powershell
git apply --check PFAD/ZU/winklar-v2.patch
git apply PFAD/ZU/winklar-v2.patch
```

Alternativ enthält `files/` die betroffenen vollständigen Dateien in ihrer ursprünglichen Ordnerstruktur. Auch die neue Datei `Schussreihenfolge.php` muss auf den Server gelangen. Die Testdateien brauchen nicht auf einen produktiven Webserver kopiert zu werden.

Es ist keine neue Datenbankmigration enthalten. Der bereits vorhandene eindeutige Index `uq_schussdaten_anlass_import_hash` auf `(id_anlass, import_hash)` muss in der produktiven Datenbank existieren. Er ermöglicht den Wiederabgleich ohne doppelte Schüsse. V2 ist hinsichtlich der Importantwort auch mit dem geprüften Ausgangsstand kompatibel; für korrekte Auswertungen bei verspäteten Schüssen ist diese Sortierkorrektur notwendig.

## Prüfung

Alle PHP-Testdateien mit PHP 8.3 ausführen, insbesondere:

```text
php tests/schussreihenfolge.php
php tests/serienwertung.php
```

Die Tests wurden lokal in einem PHP-8.3-Container erfolgreich ausgeführt. Es wurde keine produktive Datenbank angesprochen. Bereits falsch datierte oder anderweitig beschädigte Serverdatensätze werden durch diesen Patch nicht gelöscht oder automatisch repariert.
