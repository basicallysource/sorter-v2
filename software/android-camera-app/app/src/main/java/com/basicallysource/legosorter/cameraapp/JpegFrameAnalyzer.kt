package com.basicallysource.legosorter.cameraapp

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.ImageFormat
import android.graphics.Matrix
import android.graphics.Rect
import android.graphics.YuvImage
import android.os.SystemClock
import android.util.Log
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import java.io.ByteArrayOutputStream

class JpegFrameAnalyzer(
    private val frameStore: LatestFrameStore,
    private val jpegQuality: Int = 80,
    private val maxFramesPerSecond: Int = 12,
) : ImageAnalysis.Analyzer {
    private val minFrameIntervalMs = 1000L / maxFramesPerSecond.coerceAtLeast(1)
    private var lastEncodedAtMs = 0L

    override fun analyze(image: ImageProxy) {
        try {
            val now = SystemClock.elapsedRealtime()
            if (now - lastEncodedAtMs < minFrameIntervalMs) {
                return
            }

            val jpeg = imageProxyToJpeg(image, jpegQuality)
            if (jpeg != null) {
                frameStore.update(jpeg)
                lastEncodedAtMs = now
            }
        } catch (e: Exception) {
            Log.w(TAG, "Failed to encode frame", e)
        } finally {
            image.close()
        }
    }

    private fun imageProxyToJpeg(image: ImageProxy, quality: Int): ByteArray? {
        val nv21 = yuv420888ToNv21(image)
        val yuvImage = YuvImage(nv21, ImageFormat.NV21, image.width, image.height, null)
        val output = ByteArrayOutputStream()
        val ok = yuvImage.compressToJpeg(Rect(0, 0, image.width, image.height), quality, output)
        if (!ok) return null

        val jpegBytes = output.toByteArray()
        return rotateJpegIfNeeded(jpegBytes, image.imageInfo.rotationDegrees, quality)
    }

    private fun rotateJpegIfNeeded(jpeg: ByteArray, rotationDegrees: Int, quality: Int): ByteArray {
        if (rotationDegrees == 0) return jpeg

        val original = BitmapFactory.decodeByteArray(jpeg, 0, jpeg.size) ?: return jpeg
        val matrix = Matrix().apply { postRotate(rotationDegrees.toFloat()) }
        val rotated = Bitmap.createBitmap(original, 0, 0, original.width, original.height, matrix, true)
        val output = ByteArrayOutputStream()
        rotated.compress(Bitmap.CompressFormat.JPEG, quality, output)
        original.recycle()
        rotated.recycle()
        return output.toByteArray()
    }

    private fun yuv420888ToNv21(image: ImageProxy): ByteArray {
        val width = image.width
        val height = image.height
        val yPlane = unpackPlane(image.planes[0], width, height)
        val uPlane = unpackPlane(image.planes[1], width / 2, height / 2)
        val vPlane = unpackPlane(image.planes[2], width / 2, height / 2)

        val nv21 = ByteArray(yPlane.size + uPlane.size + vPlane.size)
        System.arraycopy(yPlane, 0, nv21, 0, yPlane.size)

        var offset = yPlane.size
        for (i in uPlane.indices) {
            nv21[offset++] = vPlane[i]
            nv21[offset++] = uPlane[i]
        }
        return nv21
    }

    private fun unpackPlane(plane: ImageProxy.PlaneProxy, width: Int, height: Int): ByteArray {
        val buffer = plane.buffer.duplicate()
        buffer.rewind()

        val rowStride = plane.rowStride
        val pixelStride = plane.pixelStride
        val rowData = ByteArray(rowStride)
        val out = ByteArray(width * height)
        var offset = 0

        for (row in 0 until height) {
            val bytesToRead = minOf(rowStride, buffer.remaining())
            buffer.get(rowData, 0, bytesToRead)
            for (col in 0 until width) {
                val srcIndex = col * pixelStride
                if (srcIndex < bytesToRead && offset < out.size) {
                    out[offset++] = rowData[srcIndex]
                }
            }
        }

        return if (offset == out.size) out else out.copyOf(offset)
    }

    companion object {
        private const val TAG = "JpegFrameAnalyzer"
    }
}
