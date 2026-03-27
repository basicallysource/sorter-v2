package com.basicallysource.legosorter.cameraapp

import android.content.Context
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraMetadata
import android.hardware.camera2.CaptureRequest
import android.util.Log
import androidx.camera.camera2.interop.Camera2CameraControl
import androidx.camera.camera2.interop.Camera2CameraInfo
import androidx.camera.camera2.interop.CaptureRequestOptions
import androidx.camera.core.Camera
import androidx.camera.extensions.ExtensionMode
import org.json.JSONArray
import org.json.JSONObject

data class AndroidCameraSettings(
    val exposureCompensation: Int = 0,
    val aeLock: Boolean = false,
    val awbLock: Boolean = false,
    val whiteBalanceMode: String = "auto",
    val processingMode: String = "standard",
)

data class AndroidCameraCapabilities(
    val exposureMin: Int = 0,
    val exposureMax: Int = 0,
    val exposureStep: Float = 1.0f,
    val supportsAeLock: Boolean = false,
    val supportsAwbLock: Boolean = false,
    val whiteBalanceModes: List<String> = listOf("auto"),
    val processingModes: List<String> = listOf("standard"),
    val supportsHdrSceneMode: Boolean = false,
    val supportsHdrExtension: Boolean = false,
    val supportsNightExtension: Boolean = false,
    val supportsAutoExtension: Boolean = false,
    val imageAnalysisSupportedModes: List<String> = listOf("standard"),
)

data class ExtensionAvailability(
    val hdr: Boolean = false,
    val night: Boolean = false,
    val auto: Boolean = false,
    val hdrImageAnalysis: Boolean = false,
    val nightImageAnalysis: Boolean = false,
    val autoImageAnalysis: Boolean = false,
)

class AndroidCameraSettingsController(
    context: Context,
    private val onProcessingModeChanged: ((String) -> Unit)? = null,
) {
    private val appContext = context.applicationContext
    private val prefs = appContext.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
    private val lock = Any()

    private var lensFacing: Int = CameraCharacteristics.LENS_FACING_BACK
    private var camera: Camera? = null
    private var capabilities = AndroidCameraCapabilities()
    private var currentSettings = AndroidCameraSettings()

    fun onCameraBound(camera: Camera, lensFacing: Int, availability: ExtensionAvailability) {
        val nextCapabilities = enrichCapabilities(queryCapabilities(camera), availability)
        val nextSettings = normalize(loadSettings(lensFacing), nextCapabilities)
        synchronized(lock) {
            this.camera = camera
            this.lensFacing = lensFacing
            this.capabilities = nextCapabilities
            this.currentSettings = nextSettings
        }
        applyToCamera(nextSettings)
    }

    fun onCameraUnbound() {
        synchronized(lock) {
            camera = null
        }
    }

    fun getSettingsResponse(): String {
        val state =
            synchronized(lock) {
                Pair(currentSettings, capabilities)
            }

        return JSONObject()
            .put("ok", true)
            .put("provider", "android-camera-app")
            .put("settings", settingsToJson(state.first))
            .put("capabilities", capabilitiesToJson(state.second))
            .toString()
    }

    fun previewSettings(body: String): String {
        val next = parseSettings(body)
        val previousProcessingMode =
            synchronized(lock) {
                currentSettings.processingMode
            }
        synchronized(lock) {
            currentSettings = next
        }
        applyToCamera(next)
        if (previousProcessingMode != next.processingMode) {
            onProcessingModeChanged?.invoke(next.processingMode)
        }
        return JSONObject()
            .put("ok", true)
            .put("provider", "android-camera-app")
            .put("settings", settingsToJson(next))
            .put("persisted", false)
            .toString()
    }

    fun saveSettings(body: String): String {
        val next = parseSettings(body)
        val previousProcessingMode =
            synchronized(lock) {
                currentSettings.processingMode
            }
        synchronized(lock) {
            currentSettings = next
            saveSettingsForLens(lensFacing, next)
        }
        applyToCamera(next)
        if (previousProcessingMode != next.processingMode) {
            onProcessingModeChanged?.invoke(next.processingMode)
        }
        return JSONObject()
            .put("ok", true)
            .put("provider", "android-camera-app")
            .put("settings", settingsToJson(next))
            .put("persisted", true)
            .toString()
    }

    private fun parseSettings(body: String): AndroidCameraSettings {
        val raw =
            try {
                JSONObject(body)
            } catch (_: Exception) {
                JSONObject()
            }

        val currentState =
            synchronized(lock) {
                currentSettings
            }

        return normalize(
            AndroidCameraSettings(
                exposureCompensation = raw.optInt("exposure_compensation", currentState.exposureCompensation),
                aeLock = raw.optBoolean("ae_lock", currentState.aeLock),
                awbLock = raw.optBoolean("awb_lock", currentState.awbLock),
                whiteBalanceMode = raw.optString("white_balance_mode", currentState.whiteBalanceMode),
                processingMode = raw.optString("processing_mode", currentState.processingMode),
            ),
            synchronized(lock) { capabilities },
        )
    }

    private fun normalize(
        settings: AndroidCameraSettings,
        capabilities: AndroidCameraCapabilities,
    ): AndroidCameraSettings {
        val exposure =
            settings.exposureCompensation.coerceIn(
                capabilities.exposureMin,
                capabilities.exposureMax,
            )
        val whiteBalance =
            settings.whiteBalanceMode.takeIf { capabilities.whiteBalanceModes.contains(it) } ?: "auto"
        val processingMode =
            settings.processingMode.takeIf { capabilities.processingModes.contains(it) } ?: "standard"

        return AndroidCameraSettings(
            exposureCompensation = exposure,
            aeLock = capabilities.supportsAeLock && settings.aeLock,
            awbLock = capabilities.supportsAwbLock && settings.awbLock,
            whiteBalanceMode = whiteBalance,
            processingMode = processingMode,
        )
    }

    private fun enrichCapabilities(
        capabilities: AndroidCameraCapabilities,
        availability: ExtensionAvailability,
    ): AndroidCameraCapabilities {
        val processingModes = mutableListOf("standard")
        if (availability.auto) processingModes += "auto"
        if (availability.hdr) processingModes += "hdr"
        if (availability.night) processingModes += "night"

        val imageAnalysisModes = mutableListOf("standard")
        if (availability.auto && availability.autoImageAnalysis) imageAnalysisModes += "auto"
        if (availability.hdr && availability.hdrImageAnalysis) imageAnalysisModes += "hdr"
        if (availability.night && availability.nightImageAnalysis) imageAnalysisModes += "night"

        return capabilities.copy(
            processingModes = processingModes.distinct(),
            supportsHdrSceneMode = capabilities.supportsHdrSceneMode,
            supportsHdrExtension = availability.hdr,
            supportsNightExtension = availability.night,
            supportsAutoExtension = availability.auto,
            imageAnalysisSupportedModes = imageAnalysisModes.distinct(),
        )
    }

    private fun queryCapabilities(camera: Camera): AndroidCameraCapabilities {
        val info = Camera2CameraInfo.from(camera.cameraInfo)
        val exposureState = camera.cameraInfo.exposureState
        val whiteBalanceModes =
            (info.getCameraCharacteristic(CameraCharacteristics.CONTROL_AWB_AVAILABLE_MODES) ?: intArrayOf())
                .toList()
                .mapNotNull { awbModeName(it) }
                .distinct()
                .let { if (it.isEmpty()) listOf("auto") else it }
        val sceneModes =
            info.getCameraCharacteristic(CameraCharacteristics.CONTROL_AVAILABLE_SCENE_MODES) ?: intArrayOf()
        val supportsHdrSceneMode = sceneModes.contains(CameraMetadata.CONTROL_SCENE_MODE_HDR)
        val processingModes = mutableListOf("standard")
        if (supportsHdrSceneMode) {
            processingModes += "hdr"
        }
        return AndroidCameraCapabilities(
            exposureMin = exposureState.exposureCompensationRange.lower,
            exposureMax = exposureState.exposureCompensationRange.upper,
            exposureStep = exposureState.exposureCompensationStep.toFloat(),
            supportsAeLock = info.getCameraCharacteristic(CameraCharacteristics.CONTROL_AE_LOCK_AVAILABLE) == true,
            supportsAwbLock = info.getCameraCharacteristic(CameraCharacteristics.CONTROL_AWB_LOCK_AVAILABLE) == true,
            whiteBalanceModes = whiteBalanceModes,
            processingModes = processingModes,
            supportsHdrSceneMode = supportsHdrSceneMode,
        )
    }

    private fun applyToCamera(settings: AndroidCameraSettings) {
        val boundCamera =
            synchronized(lock) {
                camera
            } ?: return

        try {
            boundCamera.cameraControl.setExposureCompensationIndex(settings.exposureCompensation)

            val builder = CaptureRequestOptions.Builder()
            builder.setCaptureRequestOption(CaptureRequest.CONTROL_AE_LOCK, settings.aeLock)
            builder.setCaptureRequestOption(CaptureRequest.CONTROL_AWB_LOCK, settings.awbLock)
            builder.setCaptureRequestOption(
                CaptureRequest.CONTROL_AWB_MODE,
                awbModeValue(settings.whiteBalanceMode),
            )

            if (settings.processingMode == "hdr" &&
                synchronized(lock) { capabilities.supportsHdrSceneMode }
            ) {
                builder.setCaptureRequestOption(
                    CaptureRequest.CONTROL_MODE,
                    CameraMetadata.CONTROL_MODE_USE_SCENE_MODE,
                )
                builder.setCaptureRequestOption(
                    CaptureRequest.CONTROL_SCENE_MODE,
                    CameraMetadata.CONTROL_SCENE_MODE_HDR,
                )
            } else {
                builder.setCaptureRequestOption(
                    CaptureRequest.CONTROL_MODE,
                    CameraMetadata.CONTROL_MODE_AUTO,
                )
                builder.setCaptureRequestOption(
                    CaptureRequest.CONTROL_SCENE_MODE,
                    CameraMetadata.CONTROL_SCENE_MODE_DISABLED,
                )
            }

            Camera2CameraControl.from(boundCamera.cameraControl).setCaptureRequestOptions(builder.build())
        } catch (e: Exception) {
            Log.w(TAG, "Failed to apply camera settings", e)
        }
    }

    private fun loadSettings(lensFacing: Int): AndroidCameraSettings {
        val raw = prefs.getString(settingsKey(lensFacing), null) ?: return AndroidCameraSettings()
        return try {
            val json = JSONObject(raw)
            AndroidCameraSettings(
                exposureCompensation = json.optInt("exposure_compensation", 0),
                aeLock = json.optBoolean("ae_lock", false),
                awbLock = json.optBoolean("awb_lock", false),
                whiteBalanceMode = json.optString("white_balance_mode", "auto"),
                processingMode = json.optString("processing_mode", "standard"),
            )
        } catch (_: Exception) {
            AndroidCameraSettings()
        }
    }

    private fun saveSettingsForLens(lensFacing: Int, settings: AndroidCameraSettings) {
        prefs
            .edit()
            .putString(settingsKey(lensFacing), settingsToJson(settings).toString())
            .apply()
    }

    private fun settingsKey(lensFacing: Int): String =
        if (lensFacing == CameraCharacteristics.LENS_FACING_FRONT) {
            PREF_SETTINGS_FRONT
        } else {
            PREF_SETTINGS_BACK
        }

    private fun settingsToJson(settings: AndroidCameraSettings): JSONObject =
        JSONObject()
            .put("exposure_compensation", settings.exposureCompensation)
            .put("ae_lock", settings.aeLock)
            .put("awb_lock", settings.awbLock)
            .put("white_balance_mode", settings.whiteBalanceMode)
            .put("processing_mode", settings.processingMode)

    private fun capabilitiesToJson(capabilities: AndroidCameraCapabilities): JSONObject =
        JSONObject()
            .put("exposure_compensation_min", capabilities.exposureMin)
            .put("exposure_compensation_max", capabilities.exposureMax)
            .put("exposure_compensation_step", capabilities.exposureStep.toDouble())
            .put("supports_ae_lock", capabilities.supportsAeLock)
            .put("supports_awb_lock", capabilities.supportsAwbLock)
            .put("supports_hdr", capabilities.processingModes.contains("hdr"))
            .put("supports_hdr_scene_mode", capabilities.supportsHdrSceneMode)
            .put("supports_hdr_extension", capabilities.supportsHdrExtension)
            .put("supports_night_extension", capabilities.supportsNightExtension)
            .put("supports_auto_extension", capabilities.supportsAutoExtension)
            .put(
                "white_balance_modes",
                JSONArray().apply {
                    capabilities.whiteBalanceModes.forEach { put(it) }
                },
            ).put(
                "processing_modes",
                JSONArray().apply {
                    capabilities.processingModes.forEach { put(it) }
                },
            ).put(
                "image_analysis_supported_modes",
                JSONArray().apply {
                    capabilities.imageAnalysisSupportedModes.forEach { put(it) }
                },
            )

    private fun awbModeName(mode: Int): String? =
        when (mode) {
            CaptureRequest.CONTROL_AWB_MODE_AUTO -> "auto"
            CaptureRequest.CONTROL_AWB_MODE_INCANDESCENT -> "incandescent"
            CaptureRequest.CONTROL_AWB_MODE_FLUORESCENT -> "fluorescent"
            CaptureRequest.CONTROL_AWB_MODE_WARM_FLUORESCENT -> "warm-fluorescent"
            CaptureRequest.CONTROL_AWB_MODE_DAYLIGHT -> "daylight"
            CaptureRequest.CONTROL_AWB_MODE_CLOUDY_DAYLIGHT -> "cloudy-daylight"
            CaptureRequest.CONTROL_AWB_MODE_TWILIGHT -> "twilight"
            CaptureRequest.CONTROL_AWB_MODE_SHADE -> "shade"
            else -> null
        }

    private fun awbModeValue(mode: String): Int =
        when (mode) {
            "incandescent" -> CaptureRequest.CONTROL_AWB_MODE_INCANDESCENT
            "fluorescent" -> CaptureRequest.CONTROL_AWB_MODE_FLUORESCENT
            "warm-fluorescent" -> CaptureRequest.CONTROL_AWB_MODE_WARM_FLUORESCENT
            "daylight" -> CaptureRequest.CONTROL_AWB_MODE_DAYLIGHT
            "cloudy-daylight" -> CaptureRequest.CONTROL_AWB_MODE_CLOUDY_DAYLIGHT
            "twilight" -> CaptureRequest.CONTROL_AWB_MODE_TWILIGHT
            "shade" -> CaptureRequest.CONTROL_AWB_MODE_SHADE
            else -> CaptureRequest.CONTROL_AWB_MODE_AUTO
        }

    companion object {
        private const val TAG = "AndroidCamSettings"
        private const val PREFS_NAME = "sorter_camera_prefs"
        private const val PREF_SETTINGS_BACK = "camera_settings_back"
        private const val PREF_SETTINGS_FRONT = "camera_settings_front"

        fun extensionModeForProcessingMode(processingMode: String): Int? =
            when (processingMode) {
                "auto" -> ExtensionMode.AUTO
                "hdr" -> ExtensionMode.HDR
                "night" -> ExtensionMode.NIGHT
                else -> null
            }
    }
}
