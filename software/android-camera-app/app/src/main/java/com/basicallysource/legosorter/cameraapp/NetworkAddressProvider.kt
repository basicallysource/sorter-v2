package com.basicallysource.legosorter.cameraapp

import java.net.Inet4Address
import java.net.NetworkInterface
import java.util.Collections

object NetworkAddressProvider {
    fun firstIpv4Address(): String? {
        return try {
            val interfaces = Collections.list(NetworkInterface.getNetworkInterfaces())
            for (networkInterface in interfaces) {
                if (!networkInterface.isUp || networkInterface.isLoopback || networkInterface.isVirtual) {
                    continue
                }
                for (address in Collections.list(networkInterface.inetAddresses)) {
                    if (address is Inet4Address && !address.isLoopbackAddress) {
                        return address.hostAddress
                    }
                }
            }
            null
        } catch (_: Exception) {
            null
        }
    }
}
