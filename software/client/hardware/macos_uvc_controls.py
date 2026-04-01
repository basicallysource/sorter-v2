from __future__ import annotations

import atexit
import ctypes
import ctypes.util
import re
from ctypes import POINTER, byref, c_int, c_uint8, c_uint16, c_void_p, cast
from dataclasses import dataclass
from typing import Any

from hardware.macos_camera_registry import MacOSCameraInfo, enumerate_macos_cameras

LIBUSB_ENDPOINT_IN = 0x80
LIBUSB_ENDPOINT_OUT = 0x00
LIBUSB_REQUEST_TYPE_CLASS = 0x20
LIBUSB_RECIPIENT_INTERFACE = 0x01
LIBUSB_BMREQ_IN = LIBUSB_ENDPOINT_IN | LIBUSB_REQUEST_TYPE_CLASS | LIBUSB_RECIPIENT_INTERFACE
LIBUSB_BMREQ_OUT = LIBUSB_ENDPOINT_OUT | LIBUSB_REQUEST_TYPE_CLASS | LIBUSB_RECIPIENT_INTERFACE
LIBUSB_SUCCESS = 0
LIBUSB_ERROR_ACCESS = -3
LIBUSB_ERROR_BUSY = -6
LIBUSB_CLASS_VIDEO = 0x0E
LIBUSB_SUBCLASS_VIDEO_CONTROL = 0x01
CS_INTERFACE_DESCRIPTOR_TYPE = 0x24
UVC_SUBTYPE_INPUT_TERMINAL = 0x02
UVC_SUBTYPE_PROCESSING_UNIT = 0x05
CAMERA_TERMINAL_TYPE = 0x0201

UVC_SET_CUR = 0x01
UVC_GET_CUR = 0x81
UVC_GET_MIN = 0x82
UVC_GET_MAX = 0x83
UVC_GET_RES = 0x84
UVC_GET_INFO = 0x86
UVC_GET_DEF = 0x87

CT_AE_MODE = 0x02
CT_EXPOSURE_TIME_ABSOLUTE = 0x04
CT_FOCUS_ABSOLUTE = 0x06
CT_FOCUS_AUTO = 0x08

PU_BACKLIGHT_COMPENSATION = 0x01
PU_BRIGHTNESS = 0x02
PU_CONTRAST = 0x03
PU_GAIN = 0x04
PU_POWER_LINE_FREQUENCY = 0x05
PU_SATURATION = 0x07
PU_SHARPNESS = 0x08
PU_GAMMA = 0x09
PU_WHITE_BALANCE_TEMPERATURE = 0x0A
PU_WHITE_BALANCE_TEMPERATURE_AUTO = 0x0B

AE_MODE_MANUAL = 0x01
AE_MODE_AUTO = 0x02

CONTROL_ORDER = [
    "auto_exposure",
    "exposure",
    "gain",
    "brightness",
    "contrast",
    "saturation",
    "sharpness",
    "gamma",
    "auto_white_balance",
    "white_balance_temperature",
    "autofocus",
    "focus",
    "power_line_frequency",
    "backlight_compensation",
]

CONTROL_LABEL_OVERRIDES = {
    "auto_exposure": "Auto Exposure",
    "auto_white_balance": "Auto White Balance",
    "autofocus": "Autofocus",
}

CONTROL_SPECS = {
    "exposure_mode": {
        "display": "Exposure Mode",
        "kind": "enum",
        "selector": CT_AE_MODE,
        "size": 1,
        "unit_key": "camera_terminal_id",
        "enum_values": [
            (AE_MODE_MANUAL, "manual"),
            (AE_MODE_AUTO, "auto"),
        ],
    },
    "exposure": {
        "display": "Exposure",
        "kind": "int",
        "selector": CT_EXPOSURE_TIME_ABSOLUTE,
        "size": 4,
        "unit_key": "camera_terminal_id",
        "clamp": True,
    },
    "focus": {
        "display": "Focus",
        "kind": "int",
        "selector": CT_FOCUS_ABSOLUTE,
        "size": 2,
        "unit_key": "camera_terminal_id",
        "clamp": True,
    },
    "autofocus": {
        "display": "Autofocus",
        "kind": "bool",
        "selector": CT_FOCUS_AUTO,
        "size": 1,
        "unit_key": "camera_terminal_id",
    },
    "backlight_compensation": {
        "display": "Backlight Compensation",
        "kind": "int",
        "selector": PU_BACKLIGHT_COMPENSATION,
        "size": 2,
        "unit_key": "processing_unit_id",
        "clamp": True,
    },
    "brightness": {
        "display": "Brightness",
        "kind": "int",
        "selector": PU_BRIGHTNESS,
        "size": 2,
        "unit_key": "processing_unit_id",
        "signed": True,
        "clamp": True,
    },
    "contrast": {
        "display": "Contrast",
        "kind": "int",
        "selector": PU_CONTRAST,
        "size": 2,
        "unit_key": "processing_unit_id",
        "clamp": True,
    },
    "gain": {
        "display": "Gain",
        "kind": "int",
        "selector": PU_GAIN,
        "size": 2,
        "unit_key": "processing_unit_id",
        "clamp": True,
    },
    "power_line_frequency": {
        "display": "Power Line Frequency",
        "kind": "int",
        "selector": PU_POWER_LINE_FREQUENCY,
        "size": 1,
        "unit_key": "processing_unit_id",
        "clamp": True,
    },
    "saturation": {
        "display": "Saturation",
        "kind": "int",
        "selector": PU_SATURATION,
        "size": 2,
        "unit_key": "processing_unit_id",
        "clamp": True,
    },
    "sharpness": {
        "display": "Sharpness",
        "kind": "int",
        "selector": PU_SHARPNESS,
        "size": 2,
        "unit_key": "processing_unit_id",
        "clamp": True,
    },
    "gamma": {
        "display": "Gamma",
        "kind": "int",
        "selector": PU_GAMMA,
        "size": 2,
        "unit_key": "processing_unit_id",
        "clamp": True,
    },
    "white_balance_temperature": {
        "display": "White Balance Temperature",
        "kind": "int",
        "selector": PU_WHITE_BALANCE_TEMPERATURE,
        "size": 2,
        "unit_key": "processing_unit_id",
        "clamp": True,
    },
    "auto_white_balance": {
        "display": "Auto White Balance",
        "kind": "bool",
        "selector": PU_WHITE_BALANCE_TEMPERATURE_AUTO,
        "size": 1,
        "unit_key": "processing_unit_id",
    },
}


class LibusbDeviceDescriptor(ctypes.Structure):
    _fields_ = [
        ("bLength", c_uint8),
        ("bDescriptorType", c_uint8),
        ("bcdUSB", c_uint16),
        ("bDeviceClass", c_uint8),
        ("bDeviceSubClass", c_uint8),
        ("bDeviceProtocol", c_uint8),
        ("bMaxPacketSize0", c_uint8),
        ("idVendor", c_uint16),
        ("idProduct", c_uint16),
        ("bcdDevice", c_uint16),
        ("iManufacturer", c_uint8),
        ("iProduct", c_uint8),
        ("iSerialNumber", c_uint8),
        ("bNumConfigurations", c_uint8),
    ]


class LibusbInterfaceDescriptor(ctypes.Structure):
    _fields_ = [
        ("bLength", c_uint8),
        ("bDescriptorType", c_uint8),
        ("bInterfaceNumber", c_uint8),
        ("bAlternateSetting", c_uint8),
        ("bNumEndpoints", c_uint8),
        ("bInterfaceClass", c_uint8),
        ("bInterfaceSubClass", c_uint8),
        ("bInterfaceProtocol", c_uint8),
        ("iInterface", c_uint8),
        ("endpoint", c_void_p),
        ("extra", POINTER(c_uint8)),
        ("extra_length", c_int),
    ]


class LibusbInterface(ctypes.Structure):
    _fields_ = [
        ("altsetting", POINTER(LibusbInterfaceDescriptor)),
        ("num_altsetting", c_int),
    ]


class LibusbConfigDescriptor(ctypes.Structure):
    _fields_ = [
        ("bLength", c_uint8),
        ("bDescriptorType", c_uint8),
        ("wTotalLength", c_uint16),
        ("bNumInterfaces", c_uint8),
        ("bConfigurationValue", c_uint8),
        ("iConfiguration", c_uint8),
        ("bmAttributes", c_uint8),
        ("MaxPower", c_uint8),
        ("interface", POINTER(LibusbInterface)),
        ("extra", POINTER(c_uint8)),
        ("extra_length", c_int),
    ]


@dataclass
class UvcCameraDescriptor:
    libusb_dev: c_void_p
    vendor_id: int
    product_id: int
    bus_number: int
    device_address: int
    location_id: int | None
    interface_number: int
    processing_unit_id: int
    camera_terminal_id: int
    product_name: str | None
    manufacturer_name: str | None

    @property
    def display_name(self) -> str:
        if self.product_name and self.manufacturer_name:
            return f"{self.manufacturer_name} {self.product_name}"
        if self.product_name:
            return self.product_name
        if self.manufacturer_name:
            return self.manufacturer_name
        return "Unknown Camera"


@dataclass
class UvcControlInfo:
    minimum: int
    maximum: int
    resolution: int
    current: int | bool
    default: int | bool
    is_capable: bool
    is_writable: bool
    kind: str


class UvcControllerError(Exception):
    pass


class UvcCameraController:
    def __init__(self, camera_descriptor: UvcCameraDescriptor):
        self.camera_descriptor = camera_descriptor
        self._lib = _get_libusb()
        self._handle = c_void_p()
        self._interface_claimed = False

    def open(self) -> None:
        result = self._lib.libusb_open(self.camera_descriptor.libusb_dev, byref(self._handle))
        if result != LIBUSB_SUCCESS:
            raise UvcControllerError(f"libusb_open failed: {result}")

        if self._lib.libusb_kernel_driver_active(self._handle, self.camera_descriptor.interface_number) == 1:
            self._lib.libusb_detach_kernel_driver(self._handle, self.camera_descriptor.interface_number)

        result = self._lib.libusb_claim_interface(self._handle, self.camera_descriptor.interface_number)
        if result == LIBUSB_SUCCESS:
            self._interface_claimed = True
            return
        if result in (LIBUSB_ERROR_ACCESS, LIBUSB_ERROR_BUSY):
            self._interface_claimed = False
            return

        self.close()
        raise UvcControllerError(f"libusb_claim_interface failed: {result}")

    def close(self) -> None:
        if self._handle:
            if self._interface_claimed:
                self._lib.libusb_release_interface(self._handle, self.camera_descriptor.interface_number)
                self._interface_claimed = False
            self._lib.libusb_close(self._handle)
            self._handle = c_void_p()

    def __enter__(self) -> "UvcCameraController":
        self.open()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def get_supported_control_ids(self) -> list[str]:
        supported: list[str] = []
        if self.get_control_info("exposure_mode").is_writable:
            supported.append("auto_exposure")
        for control_id in CONTROL_ORDER:
            if control_id == "auto_exposure":
                continue
            if self.get_control_info(control_id).is_writable:
                supported.append(control_id)
        return supported

    def get_control_info(self, control_id: str) -> UvcControlInfo:
        control_spec = _get_control_spec(control_id if control_id != "auto_exposure" else "exposure_mode")
        try:
            info_flags = self._get_raw(control_spec, UVC_GET_INFO, 1)[0]
        except UvcControllerError:
            return UvcControlInfo(0, 0, 0, False, False, False, False, control_spec["kind"])

        is_capable = bool(info_flags & 0x01)
        is_writable = bool(info_flags & 0x02)
        if not is_capable:
            return UvcControlInfo(0, 0, 0, False, False, False, False, control_spec["kind"])

        if control_id == "auto_exposure":
            mode = self.get_control("exposure_mode")
            default_mode = _safe_get_value(self, control_spec, UVC_GET_DEF, mode)
            return UvcControlInfo(
                0,
                1,
                1,
                mode != AE_MODE_MANUAL,
                default_mode != AE_MODE_MANUAL,
                True,
                is_writable,
                "bool",
            )

        current = self.get_control(control_id)
        if control_spec["kind"] == "bool":
            default_value = _safe_get_value(self, control_spec, UVC_GET_DEF, current)
            return UvcControlInfo(
                0,
                1,
                1,
                bool(current),
                bool(default_value),
                True,
                is_writable,
                "bool",
            )

        minimum = _safe_get_value(self, control_spec, UVC_GET_MIN, current)
        maximum = _safe_get_value(self, control_spec, UVC_GET_MAX, current)
        resolution = _safe_get_value(self, control_spec, UVC_GET_RES, 1)
        default_value = _safe_get_value(self, control_spec, UVC_GET_DEF, current)
        return UvcControlInfo(
            int(minimum),
            int(maximum),
            int(resolution),
            current,
            default_value,
            True,
            is_writable,
            control_spec["kind"],
        )

    def get_control(self, control_id: str) -> int | bool:
        if control_id == "auto_exposure":
            return self.get_control("exposure_mode") != AE_MODE_MANUAL

        control_spec = _get_control_spec(control_id)
        raw = self._get_raw(control_spec, UVC_GET_CUR, control_spec["size"])
        return _decode_control_value(control_spec, raw)

    def set_control(self, control_id: str, value: int | bool) -> int | bool:
        if control_id == "auto_exposure":
            return self.set_control("exposure_mode", AE_MODE_AUTO if bool(value) else AE_MODE_MANUAL)

        control_spec = _get_control_spec(control_id)
        if control_spec["kind"] == "int" and control_spec.get("clamp", False):
            value = _clamp_int_control(self, control_id, int(value))
        elif control_spec["kind"] == "bool":
            value = bool(value)
        elif control_spec["kind"] == "enum":
            value = _normalize_enum_value(control_spec, value)

        payload = _encode_control_value(control_spec, value)
        self._set_raw(control_spec, payload)
        return value

    def force_manual_exposure(self) -> None:
        if self.get_control_info("exposure_mode").is_capable:
            self.set_control("exposure_mode", AE_MODE_MANUAL)

    def _get_raw(self, control_spec: dict[str, Any], request_code: int, size: int) -> bytes:
        buffer = (c_uint8 * size)()
        transferred = self._lib.libusb_control_transfer(
            self._handle,
            LIBUSB_BMREQ_IN,
            request_code,
            control_spec["selector"] << 8,
            _build_windex(self.camera_descriptor, control_spec),
            cast(buffer, POINTER(c_uint8)),
            size,
            1000,
        )
        if transferred < 0:
            raise UvcControllerError(f"control GET failed request=0x{request_code:02x} err={transferred}")
        return bytes(buffer[:size])

    def _set_raw(self, control_spec: dict[str, Any], payload: bytes) -> None:
        size = len(payload)
        buffer = (c_uint8 * size).from_buffer_copy(payload)
        transferred = self._lib.libusb_control_transfer(
            self._handle,
            LIBUSB_BMREQ_OUT,
            UVC_SET_CUR,
            control_spec["selector"] << 8,
            _build_windex(self.camera_descriptor, control_spec),
            cast(buffer, POINTER(c_uint8)),
            size,
            1000,
        )
        if transferred < 0:
            raise UvcControllerError(
                f"control SET failed selector=0x{control_spec['selector']:02x} err={transferred}"
            )


def list_uvc_cameras() -> list[UvcCameraDescriptor]:
    lib = _get_libusb()
    context = _get_libusb_context()

    devices_ptr = POINTER(c_void_p)()
    count = lib.libusb_get_device_list(context, byref(devices_ptr))
    cameras: list[UvcCameraDescriptor] = []
    seen_keys: set[tuple[int, int, int]] = set()
    try:
        if count < 0:
            raise UvcControllerError(f"libusb_get_device_list failed: {count}")

        for index in range(count):
            dev = devices_ptr[index]
            descriptor = LibusbDeviceDescriptor()
            if lib.libusb_get_device_descriptor(dev, byref(descriptor)) != LIBUSB_SUCCESS:
                continue

            config_desc_ptr = POINTER(LibusbConfigDescriptor)()
            if lib.libusb_get_active_config_descriptor(dev, byref(config_desc_ptr)) != LIBUSB_SUCCESS:
                continue

            try:
                config_desc = config_desc_ptr.contents
                uvc_details = _find_uvc_details(config_desc)
                if not uvc_details:
                    continue

                interface_number, processing_unit_id, camera_terminal_id = uvc_details
                bus_number = int(lib.libusb_get_bus_number(dev))
                device_address = int(lib.libusb_get_device_address(dev))
                location_id = _read_location_id_from_device(lib, dev, bus_number)
                dedupe_key = (bus_number, device_address, interface_number)
                if dedupe_key in seen_keys:
                    continue
                seen_keys.add(dedupe_key)

                product_name = _read_usb_string(lib, dev, int(descriptor.iProduct))
                manufacturer_name = _read_usb_string(lib, dev, int(descriptor.iManufacturer))
                cameras.append(
                    UvcCameraDescriptor(
                        libusb_dev=dev,
                        vendor_id=int(descriptor.idVendor),
                        product_id=int(descriptor.idProduct),
                        bus_number=bus_number,
                        device_address=device_address,
                        location_id=location_id,
                        interface_number=interface_number,
                        processing_unit_id=processing_unit_id,
                        camera_terminal_id=camera_terminal_id,
                        product_name=product_name,
                        manufacturer_name=manufacturer_name,
                    )
                )
                lib.libusb_ref_device(dev)
            finally:
                lib.libusb_free_config_descriptor(config_desc_ptr)
    finally:
        if bool(devices_ptr):
            lib.libusb_free_device_list(devices_ptr, 1)
    return cameras


def unref_camera(camera_descriptor: UvcCameraDescriptor) -> None:
    _get_libusb().libusb_unref_device(camera_descriptor.libusb_dev)


def match_uvc_camera_for_index(index: int) -> UvcCameraDescriptor | None:
    avfoundation_cameras = list(enumerate_macos_cameras())
    target = next((camera for camera in avfoundation_cameras if camera.index == index), None)
    if target is None:
        return None

    uvc_cameras = list_uvc_cameras()
    selected = _match_uvc_camera(target, avfoundation_cameras, uvc_cameras)
    for descriptor in uvc_cameras:
        if descriptor is not selected:
            unref_camera(descriptor)
    return selected


def describe_controls_for_index(index: int) -> tuple[list[dict[str, Any]], dict[str, int | float | bool]]:
    descriptor = match_uvc_camera_for_index(index)
    if descriptor is None:
        return [], {}

    try:
        with UvcCameraController(descriptor) as controller:
            controls: list[dict[str, Any]] = []
            settings: dict[str, int | float | bool] = {}
            for control_id in controller.get_supported_control_ids():
                info = controller.get_control_info(control_id)
                if not info.is_capable:
                    continue
                spec = CONTROL_SPECS["exposure_mode" if control_id == "auto_exposure" else control_id]
                control = {
                    "key": control_id,
                    "label": CONTROL_LABEL_OVERRIDES.get(control_id, spec["display"]),
                    "kind": "boolean" if info.kind == "bool" else "number",
                    "value": info.current,
                    "default": info.default,
                }
                if info.kind != "bool":
                    control["min"] = info.minimum
                    control["max"] = info.maximum
                    control["step"] = max(1, info.resolution)
                controls.append(control)
                settings[control_id] = info.current
            return controls, settings
    finally:
        unref_camera(descriptor)


def apply_controls_for_index(
    index: int,
    settings: dict[str, int | float | bool],
) -> dict[str, int | float | bool]:
    descriptor = match_uvc_camera_for_index(index)
    if descriptor is None:
        return {}

    try:
        with UvcCameraController(descriptor) as controller:
            applied: dict[str, int | float | bool] = {}

            requested_auto_exposure = settings.get("auto_exposure")
            requested_auto_white_balance = settings.get("auto_white_balance")
            requested_autofocus = settings.get("autofocus")

            if "auto_exposure" in settings and controller.get_control_info("auto_exposure").is_writable:
                try:
                    applied["auto_exposure"] = bool(
                        controller.set_control("auto_exposure", settings["auto_exposure"])
                    )
                except Exception:
                    pass
            if (
                "auto_white_balance" in settings
                and controller.get_control_info("auto_white_balance").is_writable
            ):
                try:
                    applied["auto_white_balance"] = bool(
                        controller.set_control("auto_white_balance", settings["auto_white_balance"])
                    )
                except Exception:
                    pass
            if "autofocus" in settings and controller.get_control_info("autofocus").is_writable:
                try:
                    applied["autofocus"] = bool(controller.set_control("autofocus", settings["autofocus"]))
                except Exception:
                    pass

            if "exposure" in settings and requested_auto_exposure is not True:
                controller.force_manual_exposure()
                applied["auto_exposure"] = False
                applied["exposure"] = int(controller.set_control("exposure", settings["exposure"]))
            for key in (
                "gain",
                "brightness",
                "contrast",
                "saturation",
                "sharpness",
                "gamma",
                "white_balance_temperature",
                "focus",
                "power_line_frequency",
                "backlight_compensation",
            ):
                if key not in settings:
                    continue
                if key == "white_balance_temperature" and requested_auto_white_balance is True:
                    continue
                if key == "white_balance_temperature" and requested_auto_white_balance is None:
                    try:
                        controller.set_control("auto_white_balance", False)
                        applied["auto_white_balance"] = False
                    except Exception:
                        pass
                if key == "focus" and requested_autofocus is True:
                    continue
                if key == "focus" and requested_autofocus is None:
                    try:
                        controller.set_control("autofocus", False)
                        applied["autofocus"] = False
                    except Exception:
                        pass
                applied[key] = int(controller.set_control(key, settings[key]))

            # Refresh current values for any exposed controls.
            for control_id in controller.get_supported_control_ids():
                try:
                    current = controller.get_control(control_id)
                except Exception:
                    continue
                applied[control_id] = current
            return applied
    finally:
        unref_camera(descriptor)


def _normalize_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def _is_probable_external_usb_camera(camera_name: str) -> bool:
    normalized = _normalize_name(camera_name)
    if "virtual" in normalized:
        return False
    if "macbook" in normalized or "desk" in normalized or "schreibtischansicht" in normalized:
        return False
    return "usb" in normalized or "camera" in normalized or "kamera" in normalized


def _match_uvc_camera(
    target: MacOSCameraInfo,
    avfoundation_cameras: list[MacOSCameraInfo],
    uvc_cameras: list[UvcCameraDescriptor],
) -> UvcCameraDescriptor | None:
    if target.location_id is not None and target.vid is not None and target.pid is not None:
        exact_match = next(
            (
                descriptor
                for descriptor in uvc_cameras
                if descriptor.location_id == target.location_id
                and descriptor.vendor_id == target.vid
                and descriptor.product_id == target.pid
            ),
            None,
        )
        if exact_match is not None:
            return exact_match

    target_name = _normalize_name(target.name)

    for descriptor in uvc_cameras:
        display_name = _normalize_name(descriptor.display_name)
        product_name = _normalize_name(descriptor.product_name or "")
        if target_name and (target_name == display_name or target_name == product_name):
            return descriptor
        if target_name and (
            target_name in display_name
            or display_name in target_name
            or target_name in product_name
            or product_name in target_name
        ):
            return descriptor

    probable_usb_avfoundation = [
        camera for camera in avfoundation_cameras if _is_probable_external_usb_camera(camera.name)
    ]
    if target not in probable_usb_avfoundation:
        return None

    target_position = probable_usb_avfoundation.index(target)
    if 0 <= target_position < len(uvc_cameras):
        return uvc_cameras[target_position]
    return None


def _safe_get_value(controller: UvcCameraController, control_spec: dict[str, Any], request_code: int, fallback: Any) -> Any:
    try:
        raw = controller._get_raw(control_spec, request_code, control_spec["size"])
        return _decode_control_value(control_spec, raw)
    except UvcControllerError:
        return fallback


def _find_uvc_details(config_desc: LibusbConfigDescriptor) -> tuple[int, int, int] | None:
    for interface_index in range(config_desc.bNumInterfaces):
        interface = config_desc.interface[interface_index]
        for alt_index in range(interface.num_altsetting):
            altsetting = interface.altsetting[alt_index]
            if (
                altsetting.bInterfaceClass == LIBUSB_CLASS_VIDEO
                and altsetting.bInterfaceSubClass == LIBUSB_SUBCLASS_VIDEO_CONTROL
            ):
                processing_unit_id, camera_terminal_id = _extract_unit_ids(
                    altsetting.extra, altsetting.extra_length
                )
                if processing_unit_id == -1 or camera_terminal_id == -1:
                    processing_unit_id, camera_terminal_id = _extract_unit_ids(
                        config_desc.extra, config_desc.extra_length
                    )
                if processing_unit_id != -1 and camera_terminal_id != -1:
                    return int(altsetting.bInterfaceNumber), processing_unit_id, camera_terminal_id
    return None


def _extract_unit_ids(extra_ptr: POINTER(c_uint8), extra_length: int) -> tuple[int, int]:
    processing_unit_id = -1
    camera_terminal_id = -1
    if not extra_ptr or extra_length <= 0:
        return processing_unit_id, camera_terminal_id

    raw = ctypes.string_at(extra_ptr, extra_length)
    offset = 0
    while offset + 2 <= len(raw):
        length = raw[offset]
        if length == 0 or offset + length > len(raw):
            break

        if raw[offset + 1] == CS_INTERFACE_DESCRIPTOR_TYPE and length >= 4:
            subtype = raw[offset + 2]
            if subtype == UVC_SUBTYPE_PROCESSING_UNIT:
                processing_unit_id = raw[offset + 3]
            elif subtype == UVC_SUBTYPE_INPUT_TERMINAL and length >= 8:
                terminal_id = raw[offset + 3]
                terminal_type = int.from_bytes(raw[offset + 4 : offset + 6], "little")
                if terminal_type == CAMERA_TERMINAL_TYPE:
                    camera_terminal_id = terminal_id

        offset += length
    return processing_unit_id, camera_terminal_id


def _get_control_spec(control_id: str) -> dict[str, Any]:
    if control_id not in CONTROL_SPECS:
        raise UvcControllerError(f"Unknown control: {control_id}")
    return CONTROL_SPECS[control_id]


def _build_windex(camera_descriptor: UvcCameraDescriptor, control_spec: dict[str, Any]) -> int:
    unit_id = getattr(camera_descriptor, control_spec["unit_key"])
    return ((unit_id & 0xFF) << 8) | (camera_descriptor.interface_number & 0xFF)


def _decode_control_value(control_spec: dict[str, Any], raw_bytes: bytes) -> int | bool:
    if control_spec["kind"] == "bool":
        return int.from_bytes(raw_bytes, byteorder="little", signed=False) != 0
    return int.from_bytes(
        raw_bytes,
        byteorder="little",
        signed=bool(control_spec.get("signed", False)),
    )


def _encode_control_value(control_spec: dict[str, Any], value: int | bool) -> bytes:
    if control_spec["kind"] == "bool":
        return (1 if bool(value) else 0).to_bytes(control_spec["size"], byteorder="little")
    return int(value).to_bytes(
        control_spec["size"],
        byteorder="little",
        signed=bool(control_spec.get("signed", False)),
    )


def _normalize_enum_value(control_spec: dict[str, Any], value: int | str) -> int:
    if isinstance(value, str):
        label_map = {label: enum_value for enum_value, label in control_spec.get("enum_values", [])}
        if value not in label_map:
            raise UvcControllerError(f"Invalid enum label: {value}")
        return label_map[value]
    number = int(value)
    allowed_values = {enum_value for enum_value, _ in control_spec.get("enum_values", [])}
    if number not in allowed_values:
        raise UvcControllerError(f"Invalid enum value: {number}")
    return number


def _clamp_int_control(controller: UvcCameraController, control_id: str, value: int) -> int:
    info = controller.get_control_info(control_id)
    if not info.is_capable:
        raise UvcControllerError("Control not supported by camera")
    clamped = min(max(value, info.minimum), info.maximum)
    step = info.resolution if info.resolution > 0 else 1
    return info.minimum + ((clamped - info.minimum) // step) * step


def _read_usb_string(lib: Any, dev: c_void_p, string_index: int) -> str | None:
    if string_index <= 0:
        return None
    handle = c_void_p()
    result = lib.libusb_open(dev, byref(handle))
    if result != LIBUSB_SUCCESS:
        return None
    try:
        buffer = (c_uint8 * 256)()
        read_size = lib.libusb_get_string_descriptor_ascii(
            handle,
            c_uint8(string_index),
            cast(buffer, POINTER(c_uint8)),
            256,
        )
        if read_size <= 0:
            return None
        return bytes(buffer[:read_size]).decode("utf-8", errors="replace").strip() or None
    finally:
        lib.libusb_close(handle)


def _read_location_id_from_device(lib: Any, dev: c_void_p, bus_number: int) -> int | None:
    port_buffer = (c_uint8 * 8)()
    count = lib.libusb_get_port_numbers(dev, port_buffer, 8)
    if count <= 0:
        return None

    location_id = bus_number << 24
    for offset, port in enumerate(port_buffer[:count]):
        shift = 20 - (offset * 4)
        if shift < 0:
            break
        location_id |= int(port) << shift
    return location_id


_LIBUSB = None
_LIBUSB_CONTEXT = None


def _libusb_candidates() -> list[str]:
    candidates = [
        "/opt/homebrew/lib/libusb-1.0.dylib",
        "/usr/local/lib/libusb-1.0.dylib",
    ]
    discovered = ctypes.util.find_library("usb-1.0")
    if discovered:
        candidates.append(discovered)
    return candidates


def _get_libusb() -> Any:
    global _LIBUSB
    if _LIBUSB is not None:
        return _LIBUSB

    last_error: Exception | None = None
    for path in _libusb_candidates():
        try:
            lib = ctypes.CDLL(path)
            break
        except Exception as exc:
            last_error = exc
    else:
        raise UvcControllerError(f"Unable to load libusb: {last_error}")

    lib.libusb_init.argtypes = [POINTER(c_void_p)]
    lib.libusb_init.restype = c_int
    lib.libusb_exit.argtypes = [c_void_p]
    lib.libusb_exit.restype = None
    lib.libusb_get_device_list.argtypes = [c_void_p, POINTER(POINTER(c_void_p))]
    lib.libusb_get_device_list.restype = ctypes.c_ssize_t
    lib.libusb_free_device_list.argtypes = [POINTER(c_void_p), c_int]
    lib.libusb_free_device_list.restype = None
    lib.libusb_get_device_descriptor.argtypes = [c_void_p, POINTER(LibusbDeviceDescriptor)]
    lib.libusb_get_device_descriptor.restype = c_int
    lib.libusb_get_bus_number.argtypes = [c_void_p]
    lib.libusb_get_bus_number.restype = c_uint8
    lib.libusb_get_device_address.argtypes = [c_void_p]
    lib.libusb_get_device_address.restype = c_uint8
    lib.libusb_get_active_config_descriptor.argtypes = [c_void_p, POINTER(POINTER(LibusbConfigDescriptor))]
    lib.libusb_get_active_config_descriptor.restype = c_int
    lib.libusb_get_port_numbers.argtypes = [c_void_p, POINTER(c_uint8), c_int]
    lib.libusb_get_port_numbers.restype = c_int
    lib.libusb_free_config_descriptor.argtypes = [POINTER(LibusbConfigDescriptor)]
    lib.libusb_free_config_descriptor.restype = None
    lib.libusb_ref_device.argtypes = [c_void_p]
    lib.libusb_ref_device.restype = c_void_p
    lib.libusb_unref_device.argtypes = [c_void_p]
    lib.libusb_unref_device.restype = None
    lib.libusb_open.argtypes = [c_void_p, POINTER(c_void_p)]
    lib.libusb_open.restype = c_int
    lib.libusb_close.argtypes = [c_void_p]
    lib.libusb_close.restype = None
    lib.libusb_get_string_descriptor_ascii.argtypes = [c_void_p, c_uint8, POINTER(c_uint8), c_int]
    lib.libusb_get_string_descriptor_ascii.restype = c_int
    lib.libusb_kernel_driver_active.argtypes = [c_void_p, c_int]
    lib.libusb_kernel_driver_active.restype = c_int
    lib.libusb_detach_kernel_driver.argtypes = [c_void_p, c_int]
    lib.libusb_detach_kernel_driver.restype = c_int
    lib.libusb_claim_interface.argtypes = [c_void_p, c_int]
    lib.libusb_claim_interface.restype = c_int
    lib.libusb_release_interface.argtypes = [c_void_p, c_int]
    lib.libusb_release_interface.restype = c_int
    lib.libusb_control_transfer.argtypes = [
        c_void_p,
        c_uint8,
        c_uint8,
        c_uint16,
        c_uint16,
        POINTER(c_uint8),
        c_uint16,
        c_uint16,
    ]
    lib.libusb_control_transfer.restype = c_int

    _LIBUSB = lib
    return lib


def _get_libusb_context() -> c_void_p:
    global _LIBUSB_CONTEXT
    if _LIBUSB_CONTEXT is not None:
        return _LIBUSB_CONTEXT
    lib = _get_libusb()
    context = c_void_p()
    result = lib.libusb_init(byref(context))
    if result != LIBUSB_SUCCESS:
        raise UvcControllerError(f"libusb_init failed: {result}")
    _LIBUSB_CONTEXT = context
    atexit.register(_shutdown_libusb)
    return context


def _shutdown_libusb() -> None:
    global _LIBUSB_CONTEXT
    if _LIBUSB_CONTEXT is not None:
        _get_libusb().libusb_exit(_LIBUSB_CONTEXT)
        _LIBUSB_CONTEXT = None
