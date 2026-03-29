package com.basicallysource.legosorter.cameraapp

import android.util.Log
import java.io.BufferedOutputStream
import java.io.BufferedReader
import java.io.IOException
import java.io.InputStreamReader
import java.net.InetSocketAddress
import java.net.ServerSocket
import java.net.Socket
import java.net.SocketException
import java.nio.charset.StandardCharsets
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

class MjpegServer(
    val port: Int,
    private val frameStore: LatestFrameStore,
    private val cameraSettingsController: AndroidCameraSettingsController,
) {
    @Volatile
    private var running = false

    @Volatile
    private var serverSocket: ServerSocket? = null

    @Volatile
    private var acceptThread: Thread? = null

    @Volatile
    private var clientExecutor: ExecutorService? = null

    fun isRunning(): Boolean = running

    @Throws(IOException::class)
    fun start() {
        if (running) return

        val socket = ServerSocket()
        socket.reuseAddress = true
        socket.bind(InetSocketAddress("0.0.0.0", port))

        serverSocket = socket
        clientExecutor = Executors.newCachedThreadPool()
        running = true
        acceptThread =
            Thread(
                {
                    acceptLoop(socket)
                },
                "mjpeg-server-$port",
            ).apply {
                isDaemon = true
                start()
            }
    }

    fun stop() {
        running = false
        try {
            serverSocket?.close()
        } catch (_: IOException) {
        }
        serverSocket = null
        acceptThread?.join(500)
        acceptThread = null
        clientExecutor?.shutdownNow()
        clientExecutor = null
    }

    private fun acceptLoop(socket: ServerSocket) {
        while (running) {
            try {
                val client = socket.accept()
                client.tcpNoDelay = true
                client.soTimeout = 15_000
                clientExecutor?.execute { handleClient(client) }
            } catch (e: SocketException) {
                if (running) {
                    Log.w(TAG, "Accept loop interrupted", e)
                }
            } catch (e: IOException) {
                if (running) {
                    Log.w(TAG, "Accept loop failed", e)
                }
            }
        }
    }

    private fun handleClient(socket: Socket) {
        socket.use { client ->
            try {
                val request = readRequest(client) ?: return
                val output = BufferedOutputStream(client.getOutputStream())
                when {
                    request.method == "OPTIONS" -> writeEmptyResponse(output, "HTTP/1.1 204 No Content")
                    request.path == "/" -> writeIndex(output)
                    request.path == "/video" -> writeMjpegStream(output, client)
                    request.path == "/snapshot.jpg" -> writeSnapshot(output)
                    request.path == "/health" -> writeHealth(output)
                    request.path == "/camera-settings" && request.method == "GET" ->
                        writeJson(output, cameraSettingsController.getSettingsResponse())
                    request.path == "/camera-settings/preview" && request.method == "POST" ->
                        writeJson(output, cameraSettingsController.previewSettings(request.body))
                    request.path == "/camera-settings" && request.method == "POST" ->
                        writeJson(output, cameraSettingsController.saveSettings(request.body))
                    else -> writeNotFound(output)
                }
            } catch (e: IOException) {
                if (running) {
                    Log.d(TAG, "Client disconnected", e)
                }
            } catch (e: InterruptedException) {
                Thread.currentThread().interrupt()
            } catch (e: Exception) {
                Log.e(TAG, "Failed to handle request", e)
            }
        }
    }

    private fun writeIndex(output: BufferedOutputStream) {
        val body =
            """
            Sorter Camera

            Endpoints:
            - /video
            - /snapshot.jpg
            - /health
            - /camera-settings
            - /camera-settings/preview
            """.trimIndent()
        writeResponse(
            output = output,
            statusLine = "HTTP/1.1 200 OK",
            contentType = "text/plain; charset=utf-8",
            body = body.toByteArray(StandardCharsets.UTF_8),
        )
    }

    @Throws(IOException::class, InterruptedException::class)
    private fun writeMjpegStream(output: BufferedOutputStream, client: Socket) {
        writeHeaders(
            output = output,
            statusLine = "HTTP/1.1 200 OK",
            contentType = "multipart/x-mixed-replace; boundary=$BOUNDARY",
        )

        var lastTimestamp = -1L
        while (running && !client.isClosed) {
            val snapshot = frameStore.snapshot()
            if (snapshot == null) {
                Thread.sleep(75)
                continue
            }
            if (snapshot.capturedAtMs == lastTimestamp) {
                Thread.sleep(40)
                continue
            }

            output.write("--$BOUNDARY\r\n".toByteArray(StandardCharsets.US_ASCII))
            output.write("Content-Type: image/jpeg\r\n".toByteArray(StandardCharsets.US_ASCII))
            output.write(
                "Content-Length: ${snapshot.jpeg.size}\r\n\r\n".toByteArray(StandardCharsets.US_ASCII),
            )
            output.write(snapshot.jpeg)
            output.write("\r\n".toByteArray(StandardCharsets.US_ASCII))
            output.flush()
            lastTimestamp = snapshot.capturedAtMs
        }
    }

    private fun writeSnapshot(output: BufferedOutputStream) {
        val snapshot = frameStore.snapshot()
        if (snapshot == null) {
            writeResponse(
                output = output,
                statusLine = "HTTP/1.1 503 Service Unavailable",
                contentType = "text/plain; charset=utf-8",
                body = "No frame available yet.".toByteArray(StandardCharsets.UTF_8),
            )
            return
        }

        writeResponse(
            output = output,
            statusLine = "HTTP/1.1 200 OK",
            contentType = "image/jpeg",
            body = snapshot.jpeg,
        )
    }

    private fun writeHealth(output: BufferedOutputStream) {
        val snapshot = frameStore.snapshot()
        val ageMs =
            if (snapshot == null) {
                -1
            } else {
                android.os.SystemClock.elapsedRealtime() - snapshot.capturedAtMs
            }
        val body =
            """{"ok":true,"provider":"android-camera-app","running":$running,"has_frame":${snapshot != null},"frame_age_ms":$ageMs}"""
                .toByteArray(StandardCharsets.UTF_8)
        writeResponse(
            output = output,
            statusLine = "HTTP/1.1 200 OK",
            contentType = "application/json; charset=utf-8",
            body = body,
        )
    }

    private fun writeNotFound(output: BufferedOutputStream) {
        writeResponse(
            output = output,
            statusLine = "HTTP/1.1 404 Not Found",
            contentType = "text/plain; charset=utf-8",
            body = "Not found.".toByteArray(StandardCharsets.UTF_8),
        )
    }

    private fun writeJson(output: BufferedOutputStream, body: String) {
        writeResponse(
            output = output,
            statusLine = "HTTP/1.1 200 OK",
            contentType = "application/json; charset=utf-8",
            body = body.toByteArray(StandardCharsets.UTF_8),
        )
    }

    private fun writeEmptyResponse(output: BufferedOutputStream, statusLine: String) {
        writeHeaders(
            output = output,
            statusLine = statusLine,
            contentType = "text/plain; charset=utf-8",
            contentLength = 0,
        )
        output.flush()
    }

    private fun readRequest(socket: Socket): HttpRequest? {
        val reader =
            BufferedReader(
                InputStreamReader(socket.getInputStream(), StandardCharsets.UTF_8),
            )
        val requestLine = reader.readLine() ?: return null
        val requestParts = requestLine.split(" ")
        if (requestParts.size < 2) return null

        val headers = mutableMapOf<String, String>()
        while (true) {
            val line = reader.readLine() ?: return null
            if (line.isEmpty()) break
            val separator = line.indexOf(':')
            if (separator <= 0) continue
            val key = line.substring(0, separator).trim().lowercase()
            val value = line.substring(separator + 1).trim()
            headers[key] = value
        }

        val contentLength = headers["content-length"]?.toIntOrNull() ?: 0
        val body =
            if (contentLength > 0) {
                val chars = CharArray(contentLength)
                var read = 0
                while (read < contentLength) {
                    val chunk = reader.read(chars, read, contentLength - read)
                    if (chunk <= 0) break
                    read += chunk
                }
                String(chars, 0, read)
            } else {
                ""
            }

        return HttpRequest(
            method = requestParts[0].uppercase(),
            path = requestParts[1].substringBefore('?'),
            body = body,
        )
    }

    private fun writeResponse(
        output: BufferedOutputStream,
        statusLine: String,
        contentType: String,
        body: ByteArray,
    ) {
        writeHeaders(output, statusLine, contentType, body.size)
        output.write(body)
        output.flush()
    }

    private fun writeHeaders(
        output: BufferedOutputStream,
        statusLine: String,
        contentType: String,
        contentLength: Int? = null,
    ) {
        val headers = buildString {
            append(statusLine).append("\r\n")
            append("Connection: close\r\n")
            append("Cache-Control: no-cache, no-store, must-revalidate\r\n")
            append("Pragma: no-cache\r\n")
            append("Access-Control-Allow-Origin: *\r\n")
            append("Access-Control-Allow-Methods: GET, POST, OPTIONS\r\n")
            append("Access-Control-Allow-Headers: Content-Type\r\n")
            append("Content-Type: ").append(contentType).append("\r\n")
            if (contentLength != null) {
                append("Content-Length: ").append(contentLength).append("\r\n")
            }
            append("\r\n")
        }
        output.write(headers.toByteArray(StandardCharsets.US_ASCII))
        output.flush()
    }

    companion object {
        private const val TAG = "MjpegServer"
        private const val BOUNDARY = "frame"
    }
}

data class HttpRequest(
    val method: String,
    val path: String,
    val body: String,
)
