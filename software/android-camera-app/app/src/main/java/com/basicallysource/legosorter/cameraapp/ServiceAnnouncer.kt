package com.basicallysource.legosorter.cameraapp

import android.content.Context
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import android.os.Build
import android.provider.Settings
import android.util.Log

class ServiceAnnouncer(
    context: Context,
    private val onStateChanged: (String?) -> Unit = {},
) {
    private val appContext = context.applicationContext
    private val nsdManager =
        appContext.getSystemService(Context.NSD_SERVICE) as NsdManager

    @Volatile
    private var registrationListener: NsdManager.RegistrationListener? = null

    @Volatile
    private var registeredServiceName: String? = null

    fun currentServiceName(): String? = registeredServiceName

    fun start(port: Int, lensFacing: String) {
        stop()

        val serviceInfo =
            NsdServiceInfo().apply {
                serviceType = SERVICE_TYPE
                serviceName = buildBaseServiceName()
                this.port = port
                setAttribute("id", stableDeviceId())
                setAttribute("name", cameraDisplayName())
                setAttribute("model", Build.MODEL.orEmpty())
                setAttribute("lens", lensFacing)
                setAttribute("path", "/video")
                setAttribute("snapshot", "/snapshot.jpg")
                setAttribute("health", "/health")
                setAttribute("transport", "network")
            }

        val listener =
            object : NsdManager.RegistrationListener {
                override fun onServiceRegistered(serviceInfo: NsdServiceInfo) {
                    registeredServiceName = serviceInfo.serviceName
                    onStateChanged(registeredServiceName)
                }

                override fun onRegistrationFailed(serviceInfo: NsdServiceInfo, errorCode: Int) {
                    Log.w(TAG, "Service registration failed: $errorCode")
                    registeredServiceName = null
                    onStateChanged(null)
                }

                override fun onServiceUnregistered(serviceInfo: NsdServiceInfo) {
                    registeredServiceName = null
                    onStateChanged(null)
                }

                override fun onUnregistrationFailed(serviceInfo: NsdServiceInfo, errorCode: Int) {
                    Log.w(TAG, "Service unregistration failed: $errorCode")
                }
            }

        registrationListener = listener
        nsdManager.registerService(serviceInfo, NsdManager.PROTOCOL_DNS_SD, listener)
    }

    fun stop() {
        val listener = registrationListener ?: return
        registrationListener = null
        registeredServiceName = null
        try {
            nsdManager.unregisterService(listener)
        } catch (e: IllegalArgumentException) {
            Log.d(TAG, "Service was not registered anymore", e)
        } finally {
            onStateChanged(null)
        }
    }

    private fun buildBaseServiceName(): String {
        val model = Build.MODEL?.trim().orEmpty().ifBlank { "Android Camera" }
        return "Sorter Camera $model".take(63)
    }

    private fun cameraDisplayName(): String {
        val model = Build.MODEL?.trim().orEmpty().ifBlank { "Android Camera" }
        return "$model Camera"
    }

    private fun stableDeviceId(): String {
        val androidId =
            Settings.Secure.getString(appContext.contentResolver, Settings.Secure.ANDROID_ID)
        return if (androidId.isNullOrBlank()) {
            "android-camera-${Build.MODEL.orEmpty().replace(' ', '-').lowercase()}"
        } else {
            "android-camera-$androidId"
        }
    }

    companion object {
        private const val TAG = "ServiceAnnouncer"
        private const val SERVICE_TYPE = "_legosorter-camera._tcp."
    }
}
