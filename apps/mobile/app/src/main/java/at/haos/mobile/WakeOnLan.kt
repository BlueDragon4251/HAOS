package at.haos.mobile

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress

/**
 * Sends a standard Wake-on-LAN magic packet on the user's own LAN.
 *
 * Sending a UDP datagram does NOT prove that the PC woke up. The PC must support
 * WoL in firmware/driver and remain supplied with standby power. This is not
 * remote wake from cellular networks, and never contacts a cloud relay.
 */
object WakeOnLan {
    fun parseMac(mac: String): ByteArray {
        val normalized = mac.trim()
        require(Regex("(?i)^[0-9a-f]{2}([:-][0-9a-f]{2}){5}$").matches(normalized)) {
            "MAC-Adresse im Format AA:BB:CC:DD:EE:FF eingeben."
        }
        val groups = normalized.split(':', '-')
        return ByteArray(6) { groups[it].toInt(16).toByte() }.also {
            // Broadcast and multicast source addresses cannot be valid WoL NIC targets.
            require((it[0].toInt() and 1) == 0) { "Ungültige Multicast-/Broadcast-MAC." }
            require(it.any { b -> b.toInt() != 0 }) { "Die Null-MAC ist kein Gerät." }
        }
    }

    fun packet(mac: String): ByteArray {
        val address = parseMac(mac)
        return ByteArray(6 + 16 * 6).also { packet ->
            for (i in 0 until 6) packet[i] = 0xff.toByte()
            for (i in 0 until 16) address.copyInto(packet, 6 + i * 6)
        }
    }

    fun parseBroadcast(value: String): InetAddress {
        val host = value.trim()
        // A literal private LAN directed broadcast, or the limited broadcast.
        // Never DNS-resolve arbitrary hostnames into unexpected Internet targets.
        val parts = host.split(".")
        require(parts.size == 4 && parts.all { it.matches(Regex("[0-9]{1,3}")) }) {
            "IPv4-Broadcast-Adresse eingeben, z. B. 192.168.1.255."
        }
        val octets = parts.map { it.toInt() }
        require(octets.all { it in 0..255 }) { "Ungültige IPv4-Adresse." }
        val privateRange = (octets[0] == 10 ||
            (octets[0] == 172 && octets[1] in 16..31) ||
            (octets[0] == 192 && octets[1] == 168))
        require((privateRange && octets[3] == 255) || host == "255.255.255.255") {
            "Nur lokale Broadcast-Adressen (z. B. 192.168.1.255) erlaubt."
        }
        return InetAddress.getByAddress(octets.map { it.toByte() }.toByteArray())
    }

    suspend fun send(mac: String, broadcast: String, port: Int = 9) = withContext(Dispatchers.IO) {
        require(port in 1..65535) { "Ungültiger UDP-Port." }
        val payload = packet(mac)
        val address = parseBroadcast(broadcast)
        DatagramSocket().use { socket ->
            socket.broadcast = true
            socket.soTimeout = 4000
            socket.send(DatagramPacket(payload, payload.size, address, port))
        }
    }
}
