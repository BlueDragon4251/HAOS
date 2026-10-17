package at.haos.mobile

import kotlin.math.min
import kotlin.math.roundToInt

/** Maps touch input to a remote screen without cropping or guessing.
 * The host grants actual input permission separately; this object cannot send events.
 * Coordinates beyond the letterboxed area are refused, not clamped into a click.
 */
data class RemoteGeometry(
    val remoteWidth: Int,
    val remoteHeight: Int,
    val viewWidth: Float,
    val viewHeight: Float
) {
    init {
        require(remoteWidth in 1..16384 && remoteHeight in 1..16384)
        require(viewWidth.isFinite() && viewHeight.isFinite())
        require(viewWidth > 0 && viewHeight > 0)
    }

    private val scale = min(viewWidth / remoteWidth, viewHeight / remoteHeight)
    val contentWidth = remoteWidth * scale
    val contentHeight = remoteHeight * scale
    val left = (viewWidth - contentWidth) / 2f
    val top = (viewHeight - contentHeight) / 2f

    fun directTouch(x: Float, y: Float): Pair<Int, Int>? {
        if (!x.isFinite() || !y.isFinite() ||
            x < left || x > left + contentWidth ||
            y < top || y > top + contentHeight
        ) return null
        val remoteX = ((x - left) / scale).roundToInt().coerceIn(0, remoteWidth - 1)
        val remoteY = ((y - top) / scale).roundToInt().coerceIn(0, remoteHeight - 1)
        return Pair(remoteX, remoteY)
    }

    /** Trackpad-relative motion, preserving precision on small phone screens. */
    fun relativeMove(dx: Float, dy: Float, sensitivity: Float = 1f): Pair<Int, Int> {
        require(dx.isFinite() && dy.isFinite() && sensitivity.isFinite() && sensitivity in 0.1f..5f)
        return Pair((dx * sensitivity / scale).roundToInt(), (dy * sensitivity / scale).roundToInt())
    }
}
