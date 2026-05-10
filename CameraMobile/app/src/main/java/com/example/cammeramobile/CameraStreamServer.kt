package com.example.cammeramobile

import android.util.Log
import java.io.OutputStream
import java.net.ServerSocket
import java.net.Socket
import java.util.concurrent.CopyOnWriteArrayList
import kotlin.concurrent.thread

/**
 * Máy chủ TCP nhẹ để truyền luồng MJPEG từ camera điện thoại tới PC.
 * Khi PC kết nối qua ADB forward (adb forward tcp:8080 tcp:8080),
 * máy chủ gửi các khung hình JPEG theo định dạng multipart/x-mixed-replace.
 *
 * Các khung hình được gửi qua [broadcastFrame] từ luồng phân tích camera.
 */
class CameraStreamServer(
    private val port: Int,
    private val onClientCountChanged: (Int) -> Unit
) {
    companion object {
        private const val TAG = "CameraStreamServer"
        private const val BOUNDARY = "--myboundary"
    }

    private var serverSocket: ServerSocket? = null
    private val clients = CopyOnWriteArrayList<OutputStream>()
    private var running = false

    /**
     * Khởi động máy chủ TCP trong một luồng riêng.
     * Chấp nhận nhiều kết nối đồng thời.
     */
    fun start() {
        if (running) return
        running = true
        thread(name = "StreamServer") {
            try {
                serverSocket = ServerSocket(port)
                Log.i(TAG, "Máy chủ MJPEG đang lắng nghe trên cổng $port")
                while (running) {
                    try {
                        val client = serverSocket?.accept() ?: break
                        Log.i(TAG, "Client kết nối: ${client.inetAddress}")
                        // Xử lý client trong một luồng riêng
                        thread(name = "Client-${client.port}") {
                            handleClient(client)
                        }
                    } catch (e: Exception) {
                        if (running) {
                            Log.e(TAG, "Lỗi chấp nhận kết nối: ${e.message}")
                        }
                    }
                }
            } catch (e: Exception) {
                Log.e(TAG, "Lỗi khởi tạo ServerSocket: ${e.message}")
            }
        }
    }

    /**
     * Gửi một khung hình JPEG tới tất cả các client đang kết nối.
     * Định dạng MJPEG: multipart/x-mixed-replace.
     */
    fun broadcastFrame(jpegBytes: ByteArray) {
        if (clients.isEmpty()) return

        val header = (
            "$BOUNDARY\r\n" +
            "Content-Type: image/jpeg\r\n" +
            "Content-Length: ${jpegBytes.size}\r\n\r\n"
        ).toByteArray()

        val footer = "\r\n".toByteArray()

        val deadClients = mutableListOf<OutputStream>()

        for (client in clients) {
            try {
                client.write(header)
                client.write(jpegBytes)
                client.write(footer)
                client.flush()
            } catch (e: Exception) {
                Log.w(TAG, "Lỗi gửi frame tới client, đánh dấu ngắt kết nối: ${e.message}")
                deadClients.add(client)
            }
        }

        // Xóa các client đã mất kết nối
        if (deadClients.isNotEmpty()) {
            clients.removeAll(deadClients)
            deadClients.forEach {
                try { it.close() } catch (_: Exception) {}
            }
            onClientCountChanged(clients.size)
        }
    }

    /**
     * Dừng máy chủ và đóng tất cả các kết nối.
     */
    fun stop() {
        running = false
        try {
            serverSocket?.close()
        } catch (_: Exception) {}
        clients.forEach {
            try { it.close() } catch (_: Exception) {}
        }
        clients.clear()
        onClientCountChanged(0)
        Log.i(TAG, "Máy chủ MJPEG đã dừng")
    }

    /**
     * Xử lý một client mới: gửi HTTP header MJPEG, sau đó nhận frame từ broadcast.
     */
    private fun handleClient(socket: Socket) {
        try {
            val outputStream = socket.getOutputStream()

            // Gửi HTTP response header cho MJPEG stream
            val httpHeader = (
                "HTTP/1.0 200 OK\r\n" +
                "Content-Type: multipart/x-mixed-replace; boundary=$BOUNDARY\r\n" +
                "Cache-Control: no-cache\r\n" +
                "Pragma: no-cache\r\n" +
                "Connection: close\r\n\r\n"
            ).toByteArray()
            outputStream.write(httpHeader)
            outputStream.flush()

            clients.add(outputStream)
            onClientCountChanged(clients.size)
            Log.i(TAG, "Client đã sẵn sàng nhận stream. Tổng client: ${clients.size}")

            // Giữ kết nối mở; khi client ngắt, ngoại lệ sẽ xảy ra trong broadcastFrame
            // và client sẽ bị xóa ở đó.
            try {
                // Đọc để phát hiện ngắt kết nối (không thực sự đọc dữ liệu)
                val inputStream = socket.getInputStream()
                while (running) {
                    if (inputStream.read() == -1) break
                }
            } catch (_: Exception) {
                // Client ngắt kết nối
            }

        } catch (e: Exception) {
            Log.e(TAG, "Lỗi xử lý client: ${e.message}")
        } finally {
            try {
                socket.close()
            } catch (_: Exception) {}
            // Đảm bảo client bị xóa
            // (broadcastFrame sẽ tự xóa khi phát hiện lỗi ghi)
        }
    }
}
