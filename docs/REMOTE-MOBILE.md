# HAOS Mobile – physisches Eigentümer-Pairing (Entwicklung)

HAOS verwendet **einen separaten TLS-1.3-Server mit verpflichtendem Client-
Zertifikat**, nicht die ungeschützte Hermes-API. Standardmäßig ist der
Beobachtungsserver ausgeschaltet. Das Netzwerk muss bereits erreichbar sein.

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
