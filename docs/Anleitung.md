# Skibasar – Anleitung

## 1. Programm starten

**Windows:** `skibasar.exe` (oder `Skibasar-starten.bat`) doppelklicken. Es öffnet sich ein schwarzes Fenster – das muss während des ganzen Basars offen bleiben. Der Browser öffnet sich automatisch unter `http://localhost:8000`.

**Linux:** im Terminal `./skibasar` starten.

Beim ersten Start fragt Windows evtl. nach einer Firewall-Freigabe: „Privatnetzwerke“ zulassen.

### Mit Telefonen im WLAN
`Skibasar-mit-Telefonen.bat` starten (Linux: `./skibasar --lan`). Im Fenster erscheinen Adresse, **PIN** und ein QR-Code. Telefon ins gleiche WLAN bringen, QR-Code scannen, PIN eingeben. Auf der Seite „Telefon“ steht die Adresse ebenfalls. Der Laptop selbst braucht keine PIN.

Optionale Einstellungen (Umgebungsvariablen): `SKIBASAR_EVENT_PIN` (feste PIN für Telefone), `SKIBASAR_ADMIN_PIN` (Admin-PIN, überschreibt die in den Einstellungen festgelegte), `SKIBASAR_DATA_DIR` (anderer Datenordner).

### Wo liegen die Daten?
Im Ordner `data` **neben** dem Programm: Datenbank, `journal.csv`, `snapshots/` und `backups/`. Diesen Ordner nie löschen, solange der Basar läuft. Das Programm beenden: Fenster schließen (oder Strg+C).

## 2. Ablauf

1. **Einstellungen** – Name und Datum des Basars, Gebühren (Angebotsgebühr und Provision, getrennt für Händler und Privatverkäufer; bei Privatverkäufern wird die Angebotsgebühr für jeden Artikel berechnet). Dort auch die **Admin-PIN** festlegen (mindestens 4 Ziffern); ohne sie sind Änderungen an abgerechneten Verkäufern und das Zurücknehmen einer Abrechnung gesperrt. Zum Ändern wird die bisherige PIN verlangt – die PIN gut aufbewahren.
2. **Händler** – Händler anlegen mit Nummernbereich (z. B. 1000–1999), CSV-Liste hochladen. Die Vorschau zeigt Fehler und die Summe; erst „Importieren“ speichert. Ein erneuter Import zeigt vorher die Unterschiede.
3. **Annahme** – Verkäufer anlegen, dann Artikel erfassen: Beschreibung, Marke, Größe, Preis, Enter. Die nächste Nummer wird groß angezeigt – den passenden Aufkleber aufkleben. „Gebühr bezahlt“ ankreuzen, wenn die Gebühr gleich bar bezahlt wird; sonst wird sie später abgezogen. Am Ende die **Verkäuferliste** drucken.
4. **Kasse** – Nummer tippen, Enter. Rote Meldung bei unbekannten, bereits verkauften oder zurückgenommenen Nummern. „Verkauf abschließen“ speichert; Beleg optional drucken. Falsche Verkäufe: unter „Verkäufe“ **stornieren** – die Artikel sind danach wieder frei.
5. **Abholung** – Verkäufer suchen (Name, Artikelnummer oder bei Händlern die Händlernummer; private Verkäufer haben keine sichtbare Verkäufernummer). Nicht verkaufte Artikel werden als zurückgegeben abgehakt. Die Vorschau ändert nichts; erst **„Abrechnung abschließen“** speichert. Danach die Rechnung drucken und unterschreiben lassen. Bei einem Irrtum gibt es auf derselben Seite **„Abrechnung zurücknehmen“** (Admin-PIN nötig): Die Abrechnung wird gelöscht, zurückgegebene Artikel sind wieder frei, die gedruckte Rechnung ist ungültig, und der Verkäufer kann neu abgerechnet werden.
6. **Übersicht** – Tabellen für Verkäufer, Artikel und Verkäufe; Fehler können jederzeit korrigiert werden. Jede Änderung steht im Protokoll. Bei bereits abgerechneten Verkäufern ist die Admin-PIN nötig.
7. **Gesamtabrechnung** – Summen für den ganzen Basar und eine Liste der noch nicht abgeholten Verkäufer.

Alle Beträge werden intern in Cent gerechnet; die Provision wird einmal pro Verkäufer auf die Verkaufssumme berechnet und kaufmännisch gerundet.

## 3. Notfallplan (wenn das Programm ausfällt)

**Vorbereitung – vor Verkaufsbeginn:**
- Unter **Sicherung → Notfallliste** ausdrucken (alle Artikel nach Nummer mit Preis und Verkäufer). Mindestens zwei Exemplare.
- Unter **Sicherung → Exportieren** einmal auf einen USB-Stick sichern.

**Wenn etwas hakt:**
1. Ruhe bewahren, die Daten sind gespeichert. Jede Änderung steht sofort in `data/journal.csv`.
2. Zuerst versuchen: Fenster schließen, Programm neu starten. Alle Daten sind wieder da.
3. Startet es nicht mehr, kann die Kasse **auf Papier** weiterlaufen: Nummern in der Notfallliste nachschlagen, verkaufte Nummern auf einer Strichliste mit Verkaufsnummer notieren.
4. Die Dateien in `data/snapshots/` (`sellers.csv`, `articles.csv`, `sales.csv`) lassen sich mit Excel oder LibreOffice öffnen (Trennzeichen `;`, UTF-8). Sie enthalten den Stand von höchstens 5 Minuten vorher; `journal.csv` listet alles danach.
5. Zum Wiederherstellen: Programm schließen, aus `data/backups/` die neueste Datei nach `data/skibasar.db` kopieren (die Dateien `skibasar.db-wal` und `skibasar.db-shm` vorher löschen), dann neu starten.
6. Nach der Reparatur Papier-Verkäufe nachtragen (Kasse) oder bei der Abholung von Hand verrechnen.

## 4. Programm selbst bauen (für Entwickler)

Jeder Build läuft auf dem Zielsystem, ein Windows-Build also auf einem Windows-Rechner. Voraussetzung: [uv](https://docs.astral.sh/uv/).

- Linux: `./packaging/build.sh` → `dist/skibasar`
- Windows: `.\packaging\build.ps1` → `dist\skibasar.exe` plus Start-Dateien

Das Ergebnis ist eine einzelne Datei ohne Python-Installation. Danach prüfen: Programm starten, Browser öffnen, Telefon über WLAN verbinden, alle Ausdrucke testen.
