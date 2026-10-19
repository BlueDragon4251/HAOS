package at.haos.mobile

import java.util.UUID

/** The server has already authenticated the mTLS client and scoped each mission.
 * The app independently refuses malformed identifiers and stale captures.
 */
object RemoteSnapshotPolicy {
    const val MAX_JPEG_BYTES = 73728
    const val MAX_CAPTURE_AGE_MILLIS = 15000L

    fun missionId(value: String): String {
        require(value.length == 36 && value == UUID.fromString(value).toString()) {
            "Eine gültige, eindeutige Mission muss ausgewählt sein."
        }
        return value
    }

    fun canDisplay(
        missionActive: Boolean,
        authorityAvailable: Boolean,
        captureTimestampSeconds: Double,
        nowMillis: Long
    ): Boolean {
        if (!missionActive || !authorityAvailable || !captureTimestampSeconds.isFinite()) return false
        val age = nowMillis.toDouble() - captureTimestampSeconds * 1000.0
        return age >= 0 && age < MAX_CAPTURE_AGE_MILLIS
    }

    fun verifyJpeg(image: ByteArray): ByteArray {
        require(image.size in 101..MAX_JPEG_BYTES &&
            image[0] == 0xff.toByte() && image[1] == 0xd8.toByte() &&
            image[image.size - 2] == 0xff.toByte() &&
            image[image.size - 1] == 0xd9.toByte()) {
            "Ungültiger oder zu großer Bildschirm-Ausschnitt."
        }
        return image
    }
}
