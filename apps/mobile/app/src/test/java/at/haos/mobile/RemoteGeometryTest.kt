package at.haos.mobile

import org.junit.Assert.*
import org.junit.Test

class RemoteGeometryTest {
    @Test fun fitDoesNotCropWideScreen() {
        val map = RemoteGeometry(1920, 1080, 360f, 800f)
        assertEquals(360f, map.contentWidth, 0.01f)
        assertEquals(202.5f, map.contentHeight, 0.1f)
        assertEquals(null, map.directTouch(180f, 150f))
        assertEquals(Pair(960, 540), map.directTouch(180f, 400f))
    }

    @Test fun exactEdgeAndLetterboxSafety() {
        val map = RemoteGeometry(1280, 720, 400f, 240f)
        assertNull(map.directTouch(-1f, 100f))
        assertNull(map.directTouch(100f, 0f))
        assertEquals(Pair(0, 0), map.directTouch(map.left, map.top))
        assertEquals(Pair(1279, 719), map.directTouch(map.left + map.contentWidth, map.top + map.contentHeight))
    }

    @Test fun pointerMovementAndInvalidScreens() {
        val map = RemoteGeometry(2000, 1000, 500f, 250f)
        assertEquals(Pair(40, -20), map.relativeMove(10f, -5f))
        assertNull(map.directTouch(Float.NaN, 20f))
        assertThrows(IllegalArgumentException::class.java) { RemoteGeometry(0, 100, 300f, 300f) }
        assertThrows(IllegalArgumentException::class.java) { map.relativeMove(10f, 10f, 100f) }
    }
}
