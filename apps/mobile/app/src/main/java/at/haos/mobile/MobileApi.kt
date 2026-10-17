package at.haos.mobile

import android.content.Context
import android.net.Uri
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import java.net.URL
import java.security.KeyStore
import java.security.cert.CertificateFactory
import javax.net.ssl.HttpsURLConnection
import javax.net.ssl.KeyManagerFactory
import javax.net.ssl.SSLContext
import javax.net.ssl.TrustManagerFactory

data class Mission(val id: String, val state: String)

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

    suspend fun missions(): List<Mission> = withContext(Dispatchers.IO) {
        val client = URL(endpoint, "/api/missions").openConnection() as HttpsURLConnection
        client.sslSocketFactory = tls.socketFactory
        client.instanceFollowRedirects = false
        client.connectTimeout = 7000
        client.readTimeout = 7000
        client.requestMethod = "GET"
        try {
            require(client.responseCode == 200) { "HAOS rejected this device (" + client.responseCode + ")." }
            val body = client.inputStream.use { it.readNBytes(1_048_577) }
            require(body.size <= 1_048_576) { "Response too large." }
            val rows = JSONArray(String(body, Charsets.UTF_8))
            require(rows.length() <= 256) { "Too many missions." }
            List(rows.length()) { index ->
                val item = rows.getJSONObject(index)
                Mission(item.getString("id"), item.optString("state", "unknown"))
            }
        } finally { client.disconnect() }
    }
}

fun readCredential(context: Context, uri: Uri): ByteArray =
    context.contentResolver.openInputStream(uri)?.use { input ->
        input.readNBytes(1_048_577).also {
            require(it.isNotEmpty() && it.size <= 1_048_576) { "Invalid credential file." }
        }
    } ?: error("Cannot open credential file.")
