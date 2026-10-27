# HAOS Mobile – physisches Eigentümer-Pairing (Entwicklung)

HAOS verwendet **einen separaten TLS-1.3-Server mit verpflichtendem Client-
Zertifikat**, nicht die ungeschützte Hermes-API. Standardmäßig ist der
Beobachtungsserver ausgeschaltet. Das Netzwerk muss bereits erreichbar sein.

## Netzwerkstand für die spätere Fernsteuerungsphase (Owner-Angabe, 27.10.2026)

Dieses Update ändert weder die Roadmap-Reihenfolge noch den Implementierungs-
oder Abnahmestand. Drei hat laut Owner „Open Internet“ aktiviert: öffentliche
**dynamische** IPv4 statt CGNAT, keine statische Adresse und kein zusätzliches
IP-Paket. Die aktuelle WAN-Adresse ist kein dauerhafter Verbindungsparameter.
ZTE G5TC, Firmware BD_G5TCV1.0.0B22: Portweiterleitung aktiviert, höchstens zehn
Regeln, TCP/UDP/TCP+UDP. Lease-Dauer und Einschränkungen eingehender Verbindungen
sind noch beim Provider angefragt.

Topologie: Drei 5G → ZTE G5TC → LAN → A1 Mesh Disc 1 → drahtloses Mesh →
A1 Mesh Disc 2 → LAN → USB-Ethernet → HP EliteBook 830 G11. Exakte Mesh- und
USB-Adaptermodelle sind noch unbekannt. Die spätere Lösung soll bestehende
mTLS-/Rollen-/Entzugsfunktionen erhalten und direkte verschlüsselte Verbindung,
Dynamic DNS, Wiederverbindung nach Adresswechsel, kontinuierlichen Desktopstream
und Eingaben im optionalen App-Onboarding berücksichtigen. VPS oder fremde
Vermittlungsdienste sollen keine Pflicht werden. Dies ist keine aktuelle
Erreichbarkeits-, Stream- oder Android-Abnahme.

**Wake-on-WAN bleibt ungeprüft.** Eine aktive USB-Ethernet-LED im ausgeschalteten
Zustand belegt weder Wake-on-LAN noch S5-Unterstützung. Später real zu prüfen:
BIOS/UEFI und Adapter einschließlich S5, Magic-Packet-Transport durch beide
Mesh-Discs, UDP-Weiterleitung/Broadcast bzw. statisches ARP des Routers sowie
Verhalten nach längerer Ausschaltzeit. Antworten von Drei zu diesen Punkten,
Mesh-Einschränkungen und IP-Wechseln stehen aus. Keine ungeschützte öffentliche
Verwaltung und keine Funktionszusage vor erfolgreichem Hardwaretest; sichere
Alternativen sind bei fehlender Router-/Hardware-Unterstützung zu bewerten.

## Einmalige Einrichtung am vertrauenswürdigen HAOS-PC

Als angemeldeter Eigentümer mit eigener Passwortbestätigung:

```sh
sudo /usr/bin/haos-owner remote bootstrap \
  --hostname 192.168.1.44 --bind 192.168.1.44 \
  --device-id mein-handy \
  --mission 00000000-0000-4000-8000-000000000001 \
  --hours 12 --share-content --share-screenshots
```

Die Mission-ID muss eine **tatsächlich vom Eigentümer freizugebende,
vorhandene Mission** sein; die angezeigte UUID ist lediglich ein
**Beispiel**. IP/Hostname müssen zur HAOS-LAN-Adresse und zum
Serverzertifikat passen. Für die PKCS#12-Datei wird zweimal am lokalen
Eigentümer-Terminal ein **mindestens 16 Zeichen langes Passwort** abgefragt;
es gelangt weder in die Shell-Argumente noch in Umgebungsvariablen oder Logs.

Der Befehl erzeugt eine lokale CA und zwei P-256-Zertifikate mit
serverAuth/clientAuth, prüft sie mit OpenSSL, speichert den CA-
Signierschlüssel und den TLS-Server-Key ausschließlich in
`/etc/haos/remote-private` (root-only). **Nur** das per Passwort
verschlüsselte Client-PKCS#12 `/var/lib/haos-owner/remote-export/mein-handy.p12`
und die öffentliche CA-Datei `mein-handy-ca.pem` müssen persönlich und
vertrauenswürdig auf das Smartphone kopiert werden. Keine automatische
Internetfreigabe, QR-PKI-Übertragung, UPnP oder fremde Relay-Dienste.

Nach Import der Dateien über **Geräte** in HAOS Mobile und Eingabe des
PKCS#12-Passworts kann die Verbindung eingerichtet werden.
Der Server muss dafür vom Eigentümer **explizit gestartet** werden:

```sh
sudo /usr/bin/haos-owner remote start
sudo /usr/bin/haos-owner remote status
```

Ein gerätegebundenes Recht gilt höchstens 24 Stunden, immer nur für
explizite Missions-UUIDs. `--share-screenshots` ermöglicht **nur**
Missions-Anwendungs-Captures, keinen vollständigen Desktop und keine Eingaben.
Ohne das Flag zeigt der Client keine Screenshots.

Widerruf, sofort auch für bereits verbundene Geräte:

```sh
sudo /usr/bin/haos-owner remote revoke mein-handy
sudo /usr/bin/haos-owner remote stop
```

Die private `.p12`-Stagingdatei nach erfolgreichem sicheren Import
vom PC löschen. Nicht in Nextcloud, unverschlüsselten Chats oder
Backups ablegen. Der Server ist mTLS-geschützt, aber direkte Freigabe im
Internet bleibt ein separates Netzwerk-/Firewall-Projekt. Bei Drei-CGNAT
kann die App den Server ohne öffentliche Erreichbarkeit nicht von
außerhalb erreichen; ein ausgeschalteter PC kann selbst keine Verbindungen
annehmen. Das hier ist eine lokale PKI-Provisionierung und ersetzt
**weder** den echten HP-Hardwaretest **noch** einen zukünftigen
Ende-zu-Ende-WAN-Fernsteuerungs-/Fernstartmechanismus.

## Grenzen

- Zertifikate werden erstmalig erstellt; bestehende PKI wird nicht
  unbemerkt überschrieben oder rotiert.
- Zum Erneuern eines abgelaufenen Gerätegrants ist bisher der
  vom Eigentümer verwaltete manuelle `remote pair`-Weg nötig.
- Zertifikatsschlüssel bleiben auf dem eigenen PC; ohne dessen Zugriff
  oder ein sicher übertragenes Paket kann das Handy sich nicht anmelden.
- Das Serverzertifikat ist standardmäßig 90 Tage gültig.

## Vorhandenen Grant gezielt erneuern

Die lokale Identität der App bleibt gleich; der Eigentümer darf eine
bestehende Freigabe **ohne weitere Berechtigungen** für maximal 24 Stunden
verlängern. Das erstellt keine neuen Schlüssel und wirkt nicht über das
Ablaufdatum des X.509-Zertifikats hinaus:

```sh
sudo /usr/bin/haos-owner remote renew mein-handy --hours 12
```

Der Vorgang wird im root-eigenen Audit protokolliert. Die konkrete
Missionsliste und Screenshot-Freigabe bleiben unverändert.
