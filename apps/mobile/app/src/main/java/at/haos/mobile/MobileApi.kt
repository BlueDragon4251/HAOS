package at.haos.mobile

import android.content.Context
import android.net.Uri
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.util.Base64
import java.net.URL
import java.security.KeyStore
import java.security.cert.CertificateFactory
import javax.net.ssl.HttpsURLConnection
import javax.net.ssl.KeyManagerFactory
import javax.net.ssl.SSLContext
import javax.net.ssl.TrustManagerFactory

data class Mission(val id: String, val state: String)

data class RemoteCapture(val program: String, val instance: String, val image: ByteArray)
data class RemoteMissionSnapshot(val mission: String, val captures: List<RemoteCapture>,
                                 val active: Boolean)
data class MissionEvent(val sequence: Long, val kind: String)


object EndpointPolicy {
    fun parse(raw: String): URL {
        require(raw.length in 12..255) { "Invalid hostname." }
        val url = URL(raw.trim())
        require(url.protocol == "https" && url.host.isNotBlank()) { "Only HTTPS is supported." }
        require(url.userInfo == null && url.query == null && url.ref == null) { "Unexpected URL components." }
        require(url.path.isEmpty() || url.path == "/") { "Use only the server address and port." }
        require(url.port == -1 || url.port in 1..65535) { "Invalid port." }
        require(url.host.all { it.isLetterOrDigit() || it in ".-:[]" }) { "Invalid hostname." }
        return URL("https", url.host, if (url.port == -1) 8443 else url.port, "/")
    }
}

/** Authenticated read-only HTTPS only. No trust-all SSL or hostname verifier override.
 * The imported CA must sign the real HAOS observer server's hostname certificate.
 * The client identity must already be explicitly granted to missions by the owner.
 */
class AuthenticatedViewer(val endpoint: URL, p12: ByteArray, secret: CharArray, ca: ByteArray) {
    private val tls = SSLContext.getInstance("TLS").apply {
        val identity = KeyStore.getInstance("PKCS12").apply { load(p12.inputStream(), secret) }
        val keys = KeyManagerFactory.getInstance(KeyManagerFactory.getDefaultAlgorithm()).apply {
            init(identity, secret)
        }
        val root = CertificateFactory.getInstance("X.509").generateCertificate(ca.inputStream())
        val roots = KeyStore.getInstance(KeyStore.getDefaultType()).apply {
            load(null, null)
            setCertificateEntry("haos-pinned-ca", root)
        }
        val trust = TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm()).apply {
            init(roots)
        }
        init(keys.keyManagers, trust.trustManagers, null)
    }

    private suspend fun readOnly(path: String): String = withContext(Dispatchers.IO) {
        val client = URL(endpoint, path).openConnection() as HttpsURLConnection
        client.sslSocketFactory = tls.socketFactory
        client.instanceFollowRedirects = false
        client.connectTimeout = 7000
        client.readTimeout = 7000
        client.requestMethod = "GET"
        try {
            require(client.responseCode == 200) {
                "HAOS: Zugriff verweigert oder Freigabe abgelaufen (HTTP ${client.responseCode})."
            }
            val body = client.inputStream.use { it.readNBytes(1_048_577) }
            require(body.size <= 1_048_576) { "Antwort des Beobachtungsservers zu groß." }
            String(body, Charsets.UTF_8)
        } finally { client.disconnect() }
    }

    suspend fun missions(): List<Mission> {
        val rows = JSONArray(readOnly("/api/missions"))
        require(rows.length() <= 256) { "Zu viele Missionen." }
        return List(rows.length()) { index ->
            val item = rows.getJSONObject(index)
            Mission(RemoteSnapshotPolicy.missionId(item.getString("id")),
                item.optString("state", "unknown").take(96))
        }
    }

    suspend fun missionEvents(missionId: String, after: Long = 0): List<MissionEvent> {
        val id = RemoteSnapshotPolicy.missionId(missionId)
        require(after >= 0) { "Ungültiger Ereigniszähler." }
        val rows = JSONArray(readOnly("/api/events/$id?after=$after"))
        require(rows.length() <= 256) { "Zu viele Ereignisse." }
        return List(rows.length()) { index ->
            val item = rows.getJSONObject(index)
            val sequence = item.getLong("seq")
            require(sequence >= 0) { "Ungültiges Ereignis." }
            MissionEvent(sequence, item.optString("kind", "event").take(96))
        }
    }

    suspend fun applicationSnapshot(missionId: String): RemoteMissionSnapshot {
        val id = RemoteSnapshotPolicy.missionId(missionId)
        val result = JSONObject(readOnly("/api/applications/$id"))
        require(result.getString("mission") == id) { "Falsche Missionszuordnung." }
        val active = result.getBoolean("mission_active")
        val authority = result.getBoolean("authority_available")
        val now = System.currentTimeMillis()
        val rows = result.getJSONArray("applications")
        require(rows.length() <= 4) { "Zu viele freigegebene Anwendungsfenster." }
        val captures = buildList {
            for (index in 0 until rows.length()) {
                val app = rows.getJSONObject(index)
                if (app.isNull("jpeg") || app.isNull("capture_at")) continue
                val at = app.getDouble("capture_at")
                if (!RemoteSnapshotPolicy.canDisplay(active, authority, at, now)) continue
                val encoded = app.getString("jpeg")
                require(encoded.length <= 98304 && encoded.startsWith("/9j/")) {
                    "Ungültige Aufnahme."
                }
                val bytes = RemoteSnapshotPolicy.verifyJpeg(Base64.getDecoder().decode(encoded))
                add(RemoteCapture(app.getString("program").take(96),
                                  app.getString("instance").take(64), bytes))
            }
        }
        return RemoteMissionSnapshot(id, captures, active && authority)
    }
}

fun readCredential(context: Context, uri: Uri): ByteArray =
    context.contentResolver.openInputStream(uri)?.use { input ->
        input.readNBytes(1_048_577).also {
            require(it.isNotEmpty() && it.size <= 1_048_576) { "Invalid credential file." }
        }
    } ?: error("Cannot open credential file.")
