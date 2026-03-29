package com.basicallysource.legosorter.cameraapp

import android.os.SystemClock

data class FrameSnapshot(
    val jpeg: ByteArray,
    val capturedAtMs: Long,
)

class LatestFrameStore {
    private val lock = Any()
    private var latestJpeg: ByteArray? = null
    private var capturedAtMs: Long = 0L

    fun update(jpeg: ByteArray) {
        synchronized(lock) {
            latestJpeg = jpeg
            capturedAtMs = SystemClock.elapsedRealtime()
        }
    }

    fun snapshot(): FrameSnapshot? =
        synchronized(lock) {
            latestJpeg?.let { FrameSnapshot(it, capturedAtMs) }
        }
}
