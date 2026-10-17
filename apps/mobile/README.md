# HAOS Mobile — native Android client

A native Kotlin Jetpack Compose application, not a WebView. Alpha 0.1 supports
connecting to HAOS's existing **read-only mTLS mission observer** with an imported
PKCS#12 client identity and pinned server CA certificate. The app does not store
credentials after exit. The host observer remains disabled by default until owner
pairing. Do not expose the observer directly on the Internet without a secure
network design.

Remote desktop, mouse/keyboard input, QR pairing, world-wide connectivity, wake,
and remote power management are **not yet supported** by the backend or client.
They must not be shown as working. Do not enable UPnP, DMZ or router WAN admin.

To build: Open apps/mobile in Android Studio. Requires JDK 17 and Android SDK 35.
CI builds a debug APK and publishes an Actions artifact.

HAOS Mobile's source and credentials remain in your control, with no required
Tailscale account or hosted relay. Direct WAN access will depend on Drei providing
a reachable address (or an explicitly accepted alternative).

## Wake-on-LAN im lokalen Netz

Im Tab **Desktop** kann die App ein standardkonformes 102-Byte-Wake-on-LAN-
Magic-Packet an eine explizite private IPv4-Broadcast-Adresse senden (UDP/9).
Sie benötigt dazu nur die **kabelgebundene MAC-Adresse** des schlafenden PCs
sowie das bereits eingerichtete WoL im UEFI/BIOS und Netzwerkadapter.
Android und PC müssen dasselbe erreichbare lokale Netzwerk verwenden.
Das Paket bestätigt keinen erfolgreichen Start und funktioniert bei CGNAT
oder aus dem Mobilfunknetz allein **nicht**. Es verwendet weder einen
Drittanbieter-Relay noch Router-Fernwartung oder automatisch konfigurierte Ports.
Zertifikate, MAC-Adresse und Broadcast-Adresse werden von der App nicht
dauerhaft gespeichert.

## Authentifizierte Beobachtung von Missions-Anwendungen

Im Desktop-Tab werden jetzt **nur** die vom Eigentümer einer expliziten
Mission zugeordneten, kurzlebigen Anwendungscaptures über
`GET /api/applications/<mission-id>` abgefragt. Die bereits bestehende
mTLS-Gerätefreigabe benötigt zusätzlich `screenshots=true` für **diese**
Mission. Bilder werden nach 15 Sekunden verworfen, sobald die Mission oder
Aufnahmeautorität nicht mehr aktiv ist, bei Berechtigungsfehlern sowie beim
Wechsel der Mission/des Tabs; sie werden nicht auf dem Telefon gespeichert.
Es gibt keine Bildschirmspiegelung aller Fenster, kein Streaming und keine
Fernsteuerung. Für den Fernzugriff über Mobilfunk muss außerdem ein
wirklich erreichbarer eigener TLS-Host existieren, was Drei/CGNAT
nicht automatisch bereitstellt. Der Betreiber kann die Freigabe jederzeit
serverseitig widerrufen.
