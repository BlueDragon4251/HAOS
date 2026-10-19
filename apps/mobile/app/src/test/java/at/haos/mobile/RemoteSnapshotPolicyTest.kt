package at.haos.mobile

import org.junit.Assert.*
import org.junit.Test

class RemoteSnapshotPolicyTest {
    private val id = "de305d54-75b4-431b-adb2-eb6b9e546014"

    @Test fun strictMissionOnly() {
        assertEquals(id, RemoteSnapshotPolicy.missionId(id))
        for (invalid in listOf("", "../root", id.uppercase(), "de305d54-75b4-431b-adb2-eb6b9e546014/..", "not-a-uuid")) {
            assertThrows(IllegalArgumentException::class.java) {
                RemoteSnapshotPolicy.missionId(invalid)
            }
        }
    }

    @Test fun captureExpiresAndRequiresCurrentOwnerGrantedMission() {
        val now = 1_000_000L
        assertTrue(RemoteSnapshotPolicy.canDisplay(true, true, 999.0, now))
        assertFalse(RemoteSnapshotPolicy.canDisplay(false, true, 999.0, now))
        assertFalse(RemoteSnapshotPolicy.canDisplay(true, false, 999.0, now))
        assertFalse(RemoteSnapshotPolicy.canDisplay(true, true, 985.0, now))
        assertFalse(RemoteSnapshotPolicy.canDisplay(true, true, 1001.0, now))
        assertFalse(RemoteSnapshotPolicy.canDisplay(true, true, Double.NaN, now))
    }

    @Test fun rejectsNonJpegAndOversizedOrEmptyFiles() {
        val jpeg = ByteArray(128) { 0x22 }
        jpeg[0] = 0xff.toByte(); jpeg[1] = 0xd8.toByte()
        jpeg[jpeg.size - 2] = 0xff.toByte(); jpeg[jpeg.size - 1] = 0xd9.toByte()
        assertArrayEquals(jpeg, RemoteSnapshotPolicy.verifyJpeg(jpeg))
        for (invalid in listOf(byteArrayOf(), ByteArray(100),
                ByteArray(RemoteSnapshotPolicy.MAX_JPEG_BYTES + 1))) {
            assertThrows(IllegalArgumentException::class.java) {
                RemoteSnapshotPolicy.verifyJpeg(invalid)
            }
        }
        jpeg[0] = 0x00
        assertThrows(IllegalArgumentException::class.java) {
            RemoteSnapshotPolicy.verifyJpeg(jpeg)
        }
    }
}
