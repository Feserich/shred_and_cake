# Skibasar – Anleitung

## 1. Programm starten

**Windows:** `skibasar.exe` (oder `Skibasar-starten.bat`) doppelklicken. Es öffnet sich ein schwarzes Fenster – **das muss während des ganzen Basars offen bleiben.** Der Browser öffnet das Programm automatisch. Fragt Windows beim ersten Start nach einer Firewall-Freigabe: „Privatnetzwerke“ zulassen.

**Linux:** Im Ordner mit dem Programm ein Terminal öffnen und `./skibasar` eingeben. Das Terminal muss während des ganzen Basars offen bleiben. Der Browser öffnet das Programm automatisch.

**Mit Telefonen:** Unter Windows stattdessen `Skibasar-mit-Telefonen.bat` starten, unter Linux `./skibasar --lan`. Im Fenster und auf der Seite **Telefon** stehen ein QR-Code und eine **PIN**. Telefon ins gleiche WLAN bringen, QR-Code scannen, PIN eingeben. Der Laptop selbst braucht keine PIN.

**Beenden:** das Fenster bzw. Terminal schließen (oder dort Strg+C drücken). Alle Daten bleiben erhalten – den Ordner `data` neben dem Programm während des Basars nie löschen.

## 2. Vorbereitung (vor dem Basar)

- **Einstellungen:** Name und Datum des Basars, Gebühren (Angebotsgebühr und Provision, getrennt für Händler und Privatverkäufer; bei Privatverkäufern gilt die Angebotsgebühr pro Artikel), erste Nummer für Privatverkäufer.
- **Admin-PIN** festlegen (Einstellungen, mindestens 4 Ziffern) und gut aufbewahren. Sie wird gebraucht, um abgerechnete Verkäufer zu ändern oder eine Abrechnung zurückzunehmen.
- **Händler** anlegen, jeweils mit eigenem Nummernbereich (z. B. 1000–1999), dann die CSV-Liste des Händlers hochladen (siehe unten).
- *Optional:* **E-Mail-Versand** einrichten (siehe unten), damit Verkäufer ihre Artikelliste und Abrechnung per E-Mail bekommen können.
- Vor Verkaufsbeginn unter **Sicherung → Notfallliste** zwei Exemplare drucken und unter **Sicherung** einmal auf einen USB-Stick exportieren.

**CSV-Liste eines Händlers:** Datei auswählen, „Vorschau“ drücken. Die Vorschau zeigt alle Artikel, Fehler (rot) und die Summe. Erst **„Import übernehmen“** speichert. Bei Fehlern in der Datei geht das nicht – Datei korrigieren und neu hochladen.

Schickt ein Händler später eine neue Liste, einfach erneut hochladen. Die Vorschau zeigt dann farbig, was **neu** (grün), **geändert** (gelb) oder **unverändert** (grau) ist. Artikel, die in der neuen Datei fehlen, sind rot durchgestrichen und werden beim Übernehmen **gelöscht** – das Programm fragt vorher nach.

Einzelne Nachlieferungen eines Händlers lassen sich auf der Händlerseite unter **„+ Artikel manuell hinzufügen“** erfassen (Nummer aus dem Bereich des Händlers). Achtung: Ein späterer CSV-Import löscht diese Artikel wieder, wenn sie nicht in der Datei stehen.

**E-Mail-Versand einrichten (optional):** Statt oder zusätzlich zum Ausdruck kann das Programm Verkäufern mit E-Mail-Adresse ihre Artikelliste (nach der Annahme) und ihre Abrechnung (nach der Abholung) schicken. Wer das nicht braucht, lässt es einfach ausgeschaltet – dann ändert sich nichts.
1. Unter **Einstellungen → E-Mail-Versand** die Zugangsdaten des Vereinspostfachs eintragen: SMTP-Server, Port, Verschlüsselung, Benutzername, Passwort, Absender-Adresse und -Name. Diese Angaben stehen beim E-Mail-Anbieter (meist unter „SMTP“ oder „E-Mail-Programm einrichten“). Üblich ist **STARTTLS mit Port 587** oder **SSL/TLS mit Port 465**.
2. Am besten ein **eigenes Vereinspostfach** oder ein **App-Passwort** verwenden (bei Gmail, GMX, web.de, Outlook usw. nötig, wenn die Zwei-Faktor-Anmeldung aktiv ist). Das Passwort wird in der Datenbank gespeichert und landet damit auch in den Sicherungen und im USB-Export.
3. **„E-Mail-Versand einschalten“** ankreuzen und speichern.
4. Mit **„Test-E-Mail senden“** an die eigene Adresse prüfen, ob alles stimmt. Klappt es nicht, steht dort der Grund (z. B. „Anmeldung abgelehnt – Benutzername oder Passwort prüfen“).

**Testdaten löschen:** Wer das Programm vorher ausprobiert hat, löscht die Testdaten vor dem echten Basar unter **Einstellungen → Alle Daten löschen**: aufklappen, zur Bestätigung `LÖSCHEN` eingeben (und die Admin-PIN, falls eingerichtet), dann **„Alle Daten unwiderruflich löschen“**. Gelöscht werden alle Verkäufer und Händler mit ihren Artikeln, alle Verkäufe, Ausgaben, die Eingaben im Abschluss und das Protokoll. Name, Datum, Gebühren und die Admin-PIN bleiben erhalten. Vorher legt das Programm automatisch eine Sicherung an. Händler danach also neu anlegen und ihre CSV-Listen erneut hochladen.

*Alternative:* Programm beenden und den Ordner `data` neben dem Programm löschen (oder umbenennen, z. B. in `data-test`). Beim nächsten Start legt das Programm einen leeren Ordner an. Dabei gehen **auch die Einstellungen, die Admin-PIN und alle Sicherungen** verloren – Einstellungen und PIN also neu eingeben. Nur bei beendetem Programm, nie während des Basars!

## 3. Am Basartag

Die Nummern entsprechen der Leiste oben im Programm.

### 1 · Annahme
1. Verkäufer suchen oder neu anlegen. Gibt es schon jemanden mit gleichem Namen, erscheint ein Hinweis – dann bitte die Adresse eintragen, damit der Verkäufer bei der Abholung eindeutig ist.
2. Artikel erfassen: Bezeichnung, Marke, Größe, Farbe, Preis, Enter. Die **nächste Nummer** wird groß angezeigt – den Kleber mit dieser Nummer auf den Artikel kleben. Bei einem Preis über 500 € fragt das Programm zur Sicherheit nach („Preis stimmt“).
3. Vertippt? **„Letzten Artikel zurücknehmen“** – die Nummer wird wieder frei.
4. Unter der Liste steht die **Angebotsgebühr**. Zahlt der Verkäufer gleich bar: „Gebühr kassiert“ drücken. Sonst wird sie bei der Abholung abgezogen.
5. **Verkäuferliste drucken** und dem Verkäufer mitgeben – *oder* per E-Mail schicken: Ist der E-Mail-Versand eingerichtet und hat der Verkäufer eine E-Mail-Adresse angegeben, steht über der Artikelliste das Kästchen **„Artikelliste per E-Mail an … senden“**. Es ist schon angehakt. Die E-Mail geht automatisch raus, sobald die Seite des Verkäufers verlassen wird – also mit dem nächsten Verkäufer oder mit „← Annahme“ bzw. der Zurück-Taste. Sie enthält alle Artikel mit Nummer und Preis, die Summe und den Stand der Angebotsgebühr. Möchte der Verkäufer keine E-Mail, einfach den Haken entfernen. Fehlt die E-Mail-Adresse, erscheint kein Kästchen – die Adresse lässt sich unter „Stammdaten“ nachtragen. Kommt der Verkäufer später mit weiteren Artikeln wieder, bekommt er beim Verlassen der Seite die aktuelle, vollständige Liste noch einmal; ohne Änderungen wird nichts doppelt verschickt. Unter dem Kästchen steht, ob die E-Mail schon **gesendet** ist oder noch **wartet**.

Lehrteam und Basarhelfer: beim Anlegen „Keine Angebotsgebühr“ ankreuzen. Die Provision auf verkaufte Artikel zahlen sie trotzdem.

### 2 · Kasse
1. Artikelnummer tippen, Enter – für jeden Artikel. Eine rote Meldung erscheint bei unbekannten oder schon verkauften Nummern.
2. Falsch eingetippt? Mit ✕ einen Artikel entfernen oder **„Letzten entfernen“**.
3. Optional bei **„Gegeben“** den Betrag des Kunden eintragen – das Programm zeigt das Rückgeld.
4. **„Verkauf abschließen“**. Beleg bei Bedarf drucken.

Falscher Verkauf schon abgeschlossen? Unter **Verkäufe** den Verkauf öffnen und **stornieren**. Die Artikel sind danach wieder verkaufbar.

### 3 · Abholung
1. Verkäufer suchen (Name, eine seiner Artikelnummern oder bei Händlern die Händlernummer).
2. Alle nicht verkauften Artikel sind schon als „zurückgegeben“ angehakt. Fehlt einer davon, den Haken entfernen (siehe „Verlorene Artikel“ unten).
3. Die Seite zeigt die Auszahlung – Gebühren und Provision sind schon abgezogen. Erst **„Abrechnung abschließen“** speichert.
4. **Rechnung drucken**, Geld auszahlen, unterschreiben lassen. Ist der E-Mail-Versand eingerichtet und hat der Verkäufer eine E-Mail-Adresse, steht über „Abrechnung abschließen“ das schon angehakte Kästchen **„Abrechnung per E-Mail an … senden“**. Beim Abschließen wird die Abrechnung dann zusätzlich oder statt des Ausdrucks per E-Mail verschickt. Möchte der Verkäufer keine E-Mail: Haken vorher entfernen.

*Optional – erst Ausrüstung zurückgeben, später auszahlen:* Hat ein Verkäufer viele Artikel, oben auf seiner Abholungsseite **„Artikelliste drucken“** wählen. Die Liste zeigt alle nicht verkauften Artikel (mit Kästchen zum Abhaken bei der Rückgabe), die verkauften Artikel und eine Unterschriftszeile „Nicht verkaufte Artikel erhalten“. Damit die Ausrüstung heraussuchen und übergeben. Das Drucken speichert nichts – die Abrechnung bleibt offen. Danach wie oben weiter: Fehlt ein Artikel, den Haken entfernen bzw. als verloren melden, dann **„Abrechnung abschließen“** und auszahlen.

### 4 · Übersicht
Tabellen mit allen Verkäufern, Artikeln und Verkäufen. Fehler lassen sich hier jederzeit korrigieren. Unter **Protokoll** steht jede Änderung. Bei bereits abgerechneten Verkäufern ist die Admin-PIN nötig.

### 5 · Abschluss (am Ende des Tages)
1. Für beide Kassen – **Basar-Kasse** und **Kuchen-Kasse** – das Wechselgeld vom Morgen und den am Ende gezählten Betrag eintragen, „Speichern“.
2. Alle **Ausgaben** eintragen (z. B. Plakate, Kuchenzutaten) und angeben, ob sie zum Basar oder zum Kuchenverkauf gehören. Wurde eine Ausgabe bar aus der Kasse bezahlt, das Häkchen setzen.
3. Die Seite zeigt den Gewinn von Basar, Kuchenverkauf und gesamt sowie beim **Kassensturz**, ob in der Basar-Kasse Geld fehlt oder zu viel ist.
4. Darunter steht die **Basar-Gesamtabrechnung** mit allen Summen und den Verkäufern, die noch nicht abgeholt haben. Die Seite **drucken**.

Solange noch nicht alle Verkäufer abgerechnet sind, ist das Ergebnis vorläufig – die Seite weist darauf hin.

## 4. Sonderfälle

**Verlorene oder gestohlene Artikel:** Fehlt bei der Abholung ein Artikel, erstattet der Verein den Preis.
1. Ganz unten auf der Abholungsseite „Artikel nicht auffindbar? (verloren / gestohlen)“ aufklappen, den Artikel ankreuzen, **„Als verloren melden“**.
2. Der Verkäufer bekommt den Preis wie bei einem Verkauf (abzüglich Provision); das steht auch auf der Rechnung. Dann wie gewohnt abrechnen.
3. Taucht der Artikel doch auf: in der Liste „Verloren“ ankreuzen, **„Doch gefunden – wieder frei“** (nur vor dem Abrechnen).

Die Erstattung erscheint im Abschluss als eigene Zeile und wird vom Gewinn abgezogen.

**Abrechnung irrtümlich abgeschlossen:** Auf der Abholungsseite des Verkäufers **„Abrechnung zurücknehmen“** (Admin-PIN nötig). Die gedruckte Rechnung ist dann ungültig; der Verkäufer kann neu abgerechnet werden. Eine noch nicht verschickte Abrechnungs-E-Mail wird dabei verworfen; eine schon verschickte lässt sich nicht zurückholen – bei der neuen Abrechnung wird mit dem angehakten Kästchen die richtige verschickt.

**E-Mails ohne Internet:** Das Programm braucht für den Basar kein Internet. Fehlt die Verbindung, wird eine E-Mail nicht verworfen, sondern **wartet**. Das Programm versucht es jede Minute erneut und verschickt wartende E-Mails automatisch, sobald wieder Internet da ist – auch nach einem Neustart des Programms. Unter **Einstellungen → E-Mail-Versand** steht die Liste aller E-Mails mit Status und Grund:
- **wartet:** wird automatisch gesendet. Mit **„Wartende jetzt senden“** sofort einen neuen Versuch starten.
- **fehlgeschlagen:** Der Mailserver hat die E-Mail abgelehnt, meist wegen einer falschen Empfängeradresse. Adresse beim Verkäufer unter „Stammdaten“ korrigieren (bei der Annahme geht die Liste beim Verlassen der Seite dann an die neue Adresse), dann die alte E-Mail hier **löschen**. Bei anderen Gründen **„Erneut“** drücken.
- Kommt dauerhaft „Anmeldung abgelehnt“: Benutzername/Passwort in den Einstellungen korrigieren – die wartenden E-Mails gehen danach von selbst raus.

**„Alle Daten löschen“** löscht auch die Liste der E-Mails, die Zugangsdaten zum Postfach bleiben erhalten.

## 5. Wenn das Programm ausfällt

1. **Ruhe bewahren** – jede Eingabe ist sofort gespeichert.
2. Programmfenster (bzw. Terminal) schließen, Programm neu starten. Alle Daten sind wieder da.
3. Startet es nicht mehr: Die Kasse läuft **auf Papier** weiter. Preise in der Notfallliste nachschlagen und für jeden verkauften Artikel Nummer und Preis aufschreiben.
4. Den Admin bzw. die technisch verantwortliche Person holen.
5. Läuft das Programm wieder: die Papier-Verkäufe an der Kasse nachtragen.

Ohne Admin geht unter **Sicherung** auch: **„Jetzt sichern“** oder **„Als ZIP herunterladen“**, um den aktuellen Stand auf einen USB-Stick zu kopieren.

---

Technische Details (Einstellungen, Datensicherung und Wiederherstellung, Programm bauen): <https://github.com/Feserich/shred_and_cake>
