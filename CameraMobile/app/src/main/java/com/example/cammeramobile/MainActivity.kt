package com.example.cammeramobile

import android.Manifest
import android.content.pm.PackageManager
import android.os.Bundle
import android.util.Log
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalLifecycleOwner
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import java.io.ByteArrayOutputStream
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

/**
 * Hoạt động chính của ứng dụng CameraMobile.
 * - Hiển thị preview camera bằng CameraX + Jetpack Compose.
 * - Cho phép chuyển đổi giữa camera trước và camera sau.
 * - Khởi động máy chủ TCP gửi luồng MJPEG tới PC qua cổng 8080.
 * - Nơi hiển thị chính và vẽ khung xương bàn tay là trên Frontend Web.
 */
class MainActivity : ComponentActivity() {

    companion object {
        private const val TAG = "CameraMobile"
        const val STREAM_PORT = 8080  // Cổng TCP chờ kết nối từ PC (qua adb forward)
    }

    private lateinit var cameraExecutor: ExecutorService
    private var streamServer: CameraStreamServer? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        cameraExecutor = Executors.newSingleThreadExecutor()

        setContent {
            CammeraMobileTheme {
                CameraApp()
            }
        }
    }

    /**
     * Giao diện chính: preview camera + nút chuyển camera + trạng thái stream.
     */
    @OptIn(ExperimentalMaterial3Api::class)
    @Composable
    fun CameraApp() {
        val context = LocalContext.current
        val lifecycleOwner = LocalLifecycleOwner.current

        // Trạng thái camera hiện tại
        var lensFacing by remember { mutableIntStateOf(CameraSelector.LENS_FACING_BACK) }
        var isStreaming by remember { mutableStateOf(false) }
        var clientCount by remember { mutableIntStateOf(0) }
        var hasCameraPermission by remember { mutableStateOf(
            ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED
        ) }

        // Launcher xin quyền camera
        val permissionLauncher = rememberLauncherForActivityResult(
            contract = ActivityResultContracts.RequestPermission()
        ) { granted ->
            hasCameraPermission = granted
            if (!granted) {
                Toast.makeText(context, "Cần quyền camera để hoạt động", Toast.LENGTH_LONG).show()
            }
        }

        // Biến lưu trữ camera provider để khởi tạo một lần
        var cameraProvider by remember { mutableStateOf<ProcessCameraProvider?>(null) }

        // Khởi tạo camera khi có quyền
        LaunchedEffect(hasCameraPermission) {
            if (hasCameraPermission && cameraProvider == null) {
                val provider = ProcessCameraProvider.getInstance(context).get()
                cameraProvider = provider
                // Bắt đầu stream server
                if (streamServer == null) {
                    streamServer = CameraStreamServer(STREAM_PORT) { count ->
                        clientCount = count
                    }
                    streamServer?.start()
                    isStreaming = true
                }
            }
        }

        // Hàm gắn camera vào PreviewView
        fun bindCamera(previewView: PreviewView, lens: Int) {
            val provider = cameraProvider ?: return
            provider.unbindAll()

            val preview = Preview.Builder().build().also {
                it.setSurfaceProvider(previewView.surfaceProvider)
            }

            val imageAnalysis = ImageAnalysis.Builder()
                .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                .build()
                .also { analysis ->
                    analysis.setAnalyzer(cameraExecutor) { imageProxy ->
                        // Chuyển đổi ImageProxy thành JPEG và gửi qua TCP
                        val buffer = imageProxy.planes[0].buffer
                        val bytes = ByteArray(buffer.remaining())
                        buffer.get(bytes)

                        // Mã hóa thành JPEG (ImageProxy thường là YUV, cần convert)
                        try {
                            val bitmap = imageProxy.toBitmap()
                            val outputStream = ByteArrayOutputStream()
                            bitmap.compress(android.graphics.Bitmap.CompressFormat.JPEG, 85, outputStream)
                            val jpegBytes = outputStream.toByteArray()
                            streamServer?.broadcastFrame(jpegBytes)
                            bitmap.recycle()
                        } catch (e: Exception) {
                            Log.e(TAG, "Lỗi mã hóa frame: ${e.message}")
                        }
                        imageProxy.close()
                    }
                }

            val cameraSelector = CameraSelector.Builder().requireLensFacing(lens).build()

            try {
                provider.bindToLifecycle(
                    lifecycleOwner,
                    cameraSelector,
                    preview,
                    imageAnalysis
                )
            } catch (e: Exception) {
                Log.e(TAG, "Lỗi gắn camera: ${e.message}")
            }
        }

        // Yêu cầu quyền khi chưa có
        if (!hasCameraPermission) {
            Column(
                modifier = Modifier.fillMaxSize(),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.Center
            ) {
                Text("Ứng dụng cần quyền truy cập camera để hoạt động")
                Spacer(modifier = Modifier.height(16.dp))
                Button(onClick = { permissionLauncher.launch(Manifest.permission.CAMERA) }) {
                    Text("Cấp quyền Camera")
                }
            }
            return
        }

        // Giao diện chính: preview + nút chuyển camera + trạng thái
        Scaffold(
            topBar = {
                TopAppBar(
                    title = { Text("CameraMobile - Stream") },
                    colors = TopAppBarDefaults.topAppBarColors(
                        containerColor = MaterialTheme.colorScheme.primaryContainer
                    )
                )
            },
            floatingActionButton = {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    FloatingActionButton(
                        onClick = {
                            lensFacing = if (lensFacing == CameraSelector.LENS_FACING_BACK) {
                                CameraSelector.LENS_FACING_FRONT
                            } else {
                                CameraSelector.LENS_FACING_BACK
                            }
                        }
                    ) {
                        Text(
                            if (lensFacing == CameraSelector.LENS_FACING_BACK) "Trước"
                            else "Sau"
                        )
                    }
                    Spacer(modifier = Modifier.height(8.dp))
                    // Hiển thị trạng thái stream
                    Surface(
                        color = MaterialTheme.colorScheme.surfaceVariant,
                        shape = MaterialTheme.shapes.small
                    ) {
                        Text(
                            text = if (isStreaming) "🟢 Port: $STREAM_PORT ($clientCount kết nối)"
                            else "🔴 Chưa stream",
                            modifier = Modifier.padding(8.dp),
                            style = MaterialTheme.typography.labelSmall
                        )
                    }
                }
            }
        ) { paddingValues ->
            // Preview camera qua AndroidView bọc PreviewView của CameraX
            AndroidView(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(paddingValues),
                factory = { ctx ->
                    PreviewView(ctx).also { previewView ->
                        previewView.post {
                            bindCamera(previewView, lensFacing)
                        }
                    }
                },
                update = { previewView ->
                    bindCamera(previewView, lensFacing)
                }
            )
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        cameraExecutor.shutdown()
        streamServer?.stop()
    }
}

/**
 * Theme Material3 đơn giản cho ứng dụng.
 */
@Composable
fun CammeraMobileTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = darkColorScheme(),
        content = content
    )
}
