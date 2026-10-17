package at.haos.mobile

import org.junit.Assert.*
import org.junit.Test

class WakeOnLanTest {
    @Test fun magicPacketIsSixFFsAndSixteenExactMacRepetitions() {
        val mac = byteArrayOf(0x02, 0x11, 0x22, 0x33, 0x44, 0x55)
        val packet = WakeOnLan.packet("02:11:22:33:44:55")
        assertEquals(102, packet.size)
        assertTrue(packet.take(6).all { it == 0xff.toByte() })
        for (copy in 0 until 16)
            assertArrayEquals(mac, packet.copyOfRange(6 + 6 * copy, 12 + 6 * copy))
        assertArrayEquals(mac, WakeOnLan.parseMac("02-11-22-33-44-55"))
    }

    @Test fun malformedMulticastAndNullMacsAreDenied() {
        for (mac in listOf("01:11:22:33:44:55", "ff:ff:ff:ff:ff:ff",
            "00:00:00:00:00:00", "02:11:22:33:44", "02:11:22:33:44:gg",
            "02:11:22:33:44:55:66", "02:11:22:33:44:55\nhello")) {
            assertThrows(IllegalArgumentException::class.java) { WakeOnLan.packet(mac) }
        }
    }

    @Test fun onlyLocalIpv4BroadcastDestinationsAreAccepted() {
        for (addr in listOf("192.168.1.255", "10.2.3.255", "172.16.0.255",
                "172.31.99.255", "255.255.255.255"))
            assertEquals(addr, WakeOnLan.parseBroadcast(addr).hostAddress)
        for (addr in listOf("8.8.8.8", "example.com", "192.168.1.20",
                "172.32.0.255", "256.1.2.255", "192.168.1.255:9", "::1",
                "192.168.1.255\nX", "127.0.0.255"))
            assertThrows(IllegalArgumentException::class.java) { WakeOnLan.parseBroadcast(addr) }
    }
}
