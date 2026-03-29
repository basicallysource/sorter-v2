package com.basicallysource.legosorter.cameraapp

import android.Manifest
import android.content.pm.PackageManager
import android.os.Bundle
import android.util.Log
import android.util.Size
import android.view.WindowManager
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.Camera
import androidx.appcompat.app.AppCompatActivity
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.Preview
import androidx.camera.extensions.ExtensionsManager
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.core.content.ContextCompat
import androidx.core.widget.doAfterTextChanged
import com.basicallysource.legosorter.cameraapp.databinding.ActivityMainBinding
import java.io.IOException
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import org.json.JSONObject

class MainActivity : AppCompatActivity() {
    private lateinit var binding: ActivityMainBinding

    private val frameStore = LatestFrameStore()
    private val cameraExecutor: ExecutorService = Executors.newSingleThreadExecutor()
    private var cameraProvider: ProcessCameraProvider? = null
    private var extensionsManager: ExtensionsManager? = null
    private var boundCamera: Camera? = null
    private var mjpegServer: MjpegServer? = null
    private lateinit var cameraSettingsController: AndroidCameraSettingsController
    private lateinit var serviceAnnouncer: ServiceAnnouncer
    private var suppressLensSwitchCallback = false

    private val permissionLauncher =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
            if (granted) {
                startCamera()
            } else {
                updateStatus("Camera permission is required to stream.")
                updateButtons()
            }
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)

        restoreSettings()
        cameraSettingsController =
            AndroidCameraSettingsController(applicationContext) {
                runOnUiThread {
                    if (hasCameraPermission()) {
                        bindCameraUseCases()
                    }
                }
            }
        serviceAnnouncer =
            ServiceAnnouncer(applicationContext) {
                runOnUiThread {
                    updateEndpointInfo()
                }
            }
        bindUi()

        if (hasCameraPermission()) {
            startCamera()
        } else {
            permissionLauncher.launch(Manifest.permission.CAMERA)
        }
    }

    override fun onDestroy() {
        stopServer()
        cameraSettingsController.onCameraUnbound()
        boundCamera = null
        cameraProvider?.unbindAll()
        cameraExecutor.shutdown()
        super.onDestroy()
    }

    private fun bindUi() {
        binding.portInput.doAfterTextChanged {
            updateEndpointInfo()
        }

        binding.frontCameraSwitch.setOnCheckedChangeListener { _, _ ->
            if (suppressLensSwitchCallback) return@setOnCheckedChangeListener
            saveSettings()
            if (hasCameraPermission()) {
                bindCameraUseCases()
            }
        }

        binding.startButton.setOnClickListener {
            startServer()
        }

        binding.stopButton.setOnClickListener {
            stopServer()
            updateStatus("Stream stopped.")
            updateButtons()
        }

        updateEndpointInfo()
        updateButtons()
    }

    private fun startCamera() {
        val providerFuture = ProcessCameraProvider.getInstance(this)
        providerFuture.addListener(
            {
                try {
                    cameraProvider = providerFuture.get()
                    initializeExtensionsAndBind()
                } catch (e: Exception) {
                    Log.e(TAG, "Failed to get camera provider", e)
                    updateStatus("Failed to initialize camera: ${e.localizedMessage ?: "unknown error"}")
                }
            },
            ContextCompat.getMainExecutor(this),
        )
    }

    private fun initializeExtensionsAndBind() {
        val provider = cameraProvider ?: return
        val future = ExtensionsManager.getInstanceAsync(applicationContext, provider)
        future.addListener(
            {
                try {
                    extensionsManager = future.get()
                } catch (e: Exception) {
                    Log.w(TAG, "Failed to initialize CameraX extensions", e)
                    extensionsManager = null
                }
                bindCameraUseCases()
            },
            ContextCompat.getMainExecutor(this),
        )
    }

    private fun bindCameraUseCases() {
        val provider = cameraProvider ?: return
        val lensFacing =
            if (binding.frontCameraSwitch.isChecked) {
                CameraSelector.LENS_FACING_FRONT
            } else {
                CameraSelector.LENS_FACING_BACK
            }

        val preview =
            Preview.Builder()
                .setTargetResolution(PREVIEW_SIZE)
                .build()
                .also { it.surfaceProvider = binding.previewView.surfaceProvider }

        val analysis =
            ImageAnalysis.Builder()
                .setTargetResolution(PREVIEW_SIZE)
                .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                .build()
                .also {
                    it.setAnalyzer(cameraExecutor, JpegFrameAnalyzer(frameStore))
                }

        val baseSelector = CameraSelector.Builder().requireLensFacing(lensFacing).build()
        val availability = extensionAvailability(baseSelector)
        val requestedProcessingMode =
            try {
                JSONObject(cameraSettingsController.getSettingsResponse())
                    .getJSONObject("settings")
                    .optString("processing_mode", "standard")
            } catch (_: Exception) {
                "standard"
            }
        val selector =
            extensionEnabledSelector(
                baseSelector = baseSelector,
                processingMode = requestedProcessingMode,
                availability = availability,
            )

        try {
            provider.unbindAll()
            val camera = provider.bindToLifecycle(this, selector, preview, analysis)
            boundCamera = camera
            cameraSettingsController.onCameraBound(camera, lensFacing, availability)
            saveSettings()
            updateStatus(
                if (binding.frontCameraSwitch.isChecked) {
                    "Front camera ready."
                } else {
                    "Back camera ready."
                },
            )
            if (mjpegServer?.isRunning() == true) {
                serviceAnnouncer.start(currentPort() ?: DEFAULT_PORT, currentLensFacingLabel())
            }
            updateEndpointInfo()
            updateButtons()
            if (mjpegServer?.isRunning() != true) {
                startServer()
            }
        } catch (e: Exception) {
            Log.e(TAG, "Failed to bind camera", e)
            cameraSettingsController.onCameraUnbound()
            boundCamera = null
            if (lensFacing == CameraSelector.LENS_FACING_FRONT) {
                suppressLensSwitchCallback = true
                binding.frontCameraSwitch.isChecked = false
                suppressLensSwitchCallback = false
                updateStatus("Front camera unavailable. Switched back to the rear camera.")
                bindCameraUseCases()
                return
            }
            updateStatus("Failed to open camera: ${e.localizedMessage ?: "unknown error"}")
        }
    }

    private fun extensionAvailability(baseSelector: CameraSelector): ExtensionAvailability {
        val manager = extensionsManager ?: return ExtensionAvailability()
        return try {
            ExtensionAvailability(
                hdr = manager.isExtensionAvailable(baseSelector, androidx.camera.extensions.ExtensionMode.HDR),
                night = manager.isExtensionAvailable(baseSelector, androidx.camera.extensions.ExtensionMode.NIGHT),
                auto = manager.isExtensionAvailable(baseSelector, androidx.camera.extensions.ExtensionMode.AUTO),
                hdrImageAnalysis = manager.isImageAnalysisSupported(baseSelector, androidx.camera.extensions.ExtensionMode.HDR),
                nightImageAnalysis = manager.isImageAnalysisSupported(baseSelector, androidx.camera.extensions.ExtensionMode.NIGHT),
                autoImageAnalysis = manager.isImageAnalysisSupported(baseSelector, androidx.camera.extensions.ExtensionMode.AUTO),
            )
        } catch (e: Exception) {
            Log.w(TAG, "Failed to query CameraX extension availability", e)
            ExtensionAvailability()
        }
    }

    private fun extensionEnabledSelector(
        baseSelector: CameraSelector,
        processingMode: String,
        availability: ExtensionAvailability,
    ): CameraSelector {
        val manager = extensionsManager ?: return baseSelector
        val extensionMode = AndroidCameraSettingsController.extensionModeForProcessingMode(processingMode)
            ?: return baseSelector

        val canUseRequestedMode =
            when (processingMode) {
                "hdr" -> availability.hdr && availability.hdrImageAnalysis
                "night" -> availability.night && availability.nightImageAnalysis
                "auto" -> availability.auto && availability.autoImageAnalysis
                else -> false
            }

        if (!canUseRequestedMode) return baseSelector

        return try {
            manager.getExtensionEnabledCameraSelector(baseSelector, extensionMode)
        } catch (e: Exception) {
            Log.w(TAG, "Failed to enable CameraX extension for mode=$processingMode", e)
            baseSelector
        }
    }

    private fun startServer() {
        val port = currentPort()
        if (port == null) {
            updateStatus("Enter a valid port between 1024 and 65535.")
            return
        }

        saveSettings()
        stopServer()

        try {
            mjpegServer = MjpegServer(port, frameStore, cameraSettingsController).also { it.start() }
            serviceAnnouncer.start(port, currentLensFacingLabel())
            updateStatus("Streaming on port $port.")
        } catch (e: IOException) {
            Log.e(TAG, "Failed to start stream server", e)
            updateStatus("Could not start server on port $port: ${e.localizedMessage ?: "unknown error"}")
        }

        updateEndpointInfo()
        updateButtons()
    }

    private fun stopServer() {
        serviceAnnouncer.stop()
        mjpegServer?.stop()
        mjpegServer = null
        updateButtons()
        updateEndpointInfo()
    }

    private fun restoreSettings() {
        val prefs = getSharedPreferences(PREFS_NAME, MODE_PRIVATE)
        binding.portInput.setText(prefs.getInt(PREF_PORT, DEFAULT_PORT).toString())
        binding.frontCameraSwitch.isChecked = prefs.getBoolean(PREF_FRONT_CAMERA, false)
    }

    private fun saveSettings() {
        val prefs = getSharedPreferences(PREFS_NAME, MODE_PRIVATE)
        prefs
            .edit()
            .putInt(PREF_PORT, currentPort() ?: DEFAULT_PORT)
            .putBoolean(PREF_FRONT_CAMERA, binding.frontCameraSwitch.isChecked)
            .apply()
    }

    private fun updateEndpointInfo() {
        val port = currentPort() ?: DEFAULT_PORT
        val baseLocal = "http://127.0.0.1:$port"
        val localIp = NetworkAddressProvider.firstIpv4Address()
        val streamUrl = "${localIp?.let { "http://$it:$port" } ?: baseLocal}/video"
        binding.urlText.text =
            getString(
                R.string.urls_template,
                streamUrl,
                "$baseLocal/snapshot.jpg",
                "$baseLocal/health",
            )
        binding.adbHintText.text = getString(R.string.adb_forward_template, port)
        binding.discoveryText.text =
            when {
                mjpegServer?.isRunning() != true -> getString(R.string.discovery_stopped)
                serviceAnnouncer.currentServiceName().isNullOrBlank() -> getString(R.string.discovery_starting)
                else ->
                    getString(
                        R.string.discovery_ready_template,
                        serviceAnnouncer.currentServiceName(),
                    )
            }
    }

    private fun updateButtons() {
        val hasPermission = hasCameraPermission()
        val running = mjpegServer?.isRunning() == true
        binding.startButton.isEnabled = hasPermission && !running
        binding.stopButton.isEnabled = running
    }

    private fun updateStatus(message: String) {
        binding.statusText.text = message
    }

    private fun currentPort(): Int? {
        val value = binding.portInput.text?.toString()?.trim().orEmpty()
        if (value.isEmpty()) return DEFAULT_PORT
        val port = value.toIntOrNull() ?: return null
        return port.takeIf { it in 1024..65535 }
    }

    private fun hasCameraPermission(): Boolean =
        ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED

    private fun currentLensFacingLabel(): String =
        if (binding.frontCameraSwitch.isChecked) {
            "front"
        } else {
            "back"
        }

    companion object {
        private const val TAG = "MainActivity"
        private const val PREFS_NAME = "sorter_camera_prefs"
        private const val PREF_PORT = "stream_port"
        private const val PREF_FRONT_CAMERA = "front_camera"
        private const val DEFAULT_PORT = 8080
        private val PREVIEW_SIZE = Size(1280, 720)
    }
}
