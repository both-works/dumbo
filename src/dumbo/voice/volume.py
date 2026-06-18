from __future__ import annotations

import ctypes
import sys
import time

VK_VOLUME_DOWN = 0xAE
VK_VOLUME_UP = 0xAF
KEYEVENTF_KEYUP = 0x0002


def set_system_volume_percent(percent: int) -> None:
    level = _validate_percent(percent)
    if sys.platform != "win32":
        raise RuntimeError("System volume control is implemented only for Windows.")

    try:
        _set_windows_core_audio_volume(level)
        return
    except Exception as core_audio_error:
        try:
            _set_windows_media_key_volume(level)
        except Exception as media_key_error:
            raise RuntimeError(
                f"Could not set Windows system volume after Core Audio failed: {core_audio_error}"
            ) from media_key_error


def _validate_percent(percent: int) -> int:
    level = int(percent)
    if not 0 <= level <= 100:
        raise ValueError("recording_volume_percent must be between 0 and 100")
    return level


def _set_windows_core_audio_volume(percent: int) -> None:
    from ctypes import POINTER, c_float, c_int, c_uint, c_void_p, c_wchar_p, cast

    from comtypes import CLSCTX_ALL, COMMETHOD, GUID, HRESULT, IUnknown
    from comtypes.client import CreateObject

    class IMMDevice(IUnknown):
        _iid_ = GUID("{D666063F-1587-4E43-81F1-B948E807363F}")
        _methods_ = [
            COMMETHOD(
                [],
                HRESULT,
                "Activate",
                (["in"], POINTER(GUID), "iid"),
                (["in"], c_uint, "dwClsCtx"),
                (["in"], c_void_p, "pActivationParams"),
                (["out"], POINTER(c_void_p), "ppInterface"),
            ),
            COMMETHOD(
                [],
                HRESULT,
                "OpenPropertyStore",
                (["in"], c_uint, "stgmAccess"),
                (["out"], POINTER(c_void_p), "ppProperties"),
            ),
            COMMETHOD([], HRESULT, "GetId", (["out"], POINTER(c_wchar_p), "ppstrId")),
            COMMETHOD([], HRESULT, "GetState", (["out"], POINTER(c_uint), "pdwState")),
        ]

    class IMMDeviceEnumerator(IUnknown):
        _iid_ = GUID("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
        _methods_ = [
            COMMETHOD(
                [],
                HRESULT,
                "EnumAudioEndpoints",
                (["in"], c_int, "dataFlow"),
                (["in"], c_uint, "dwStateMask"),
                (["out"], POINTER(c_void_p), "ppDevices"),
            ),
            COMMETHOD(
                [],
                HRESULT,
                "GetDefaultAudioEndpoint",
                (["in"], c_int, "dataFlow"),
                (["in"], c_int, "role"),
                (["out"], POINTER(POINTER(IMMDevice)), "ppEndpoint"),
            ),
            COMMETHOD(
                [],
                HRESULT,
                "GetDevice",
                (["in"], c_wchar_p, "pwstrId"),
                (["out"], POINTER(POINTER(IMMDevice)), "ppDevice"),
            ),
            COMMETHOD(
                [],
                HRESULT,
                "RegisterEndpointNotificationCallback",
                (["in"], c_void_p, "pClient"),
            ),
            COMMETHOD(
                [],
                HRESULT,
                "UnregisterEndpointNotificationCallback",
                (["in"], c_void_p, "pClient"),
            ),
        ]

    class IAudioEndpointVolume(IUnknown):
        _iid_ = GUID("{5CDF2C82-841E-4546-9722-0CF74078229A}")
        _methods_ = [
            COMMETHOD(
                [],
                HRESULT,
                "RegisterControlChangeNotify",
                (["in"], c_void_p, "pNotify"),
            ),
            COMMETHOD(
                [],
                HRESULT,
                "UnregisterControlChangeNotify",
                (["in"], c_void_p, "pNotify"),
            ),
            COMMETHOD([], HRESULT, "GetChannelCount", (["out"], POINTER(c_uint), "count")),
            COMMETHOD(
                [],
                HRESULT,
                "SetMasterVolumeLevel",
                (["in"], c_float, "level_db"),
                (["in"], POINTER(GUID), "event_context"),
            ),
            COMMETHOD(
                [],
                HRESULT,
                "SetMasterVolumeLevelScalar",
                (["in"], c_float, "level"),
                (["in"], POINTER(GUID), "event_context"),
            ),
        ]

    enumerator = CreateObject(
        GUID("{BCDE0395-E52F-467C-8E3D-C4579291692E}"),
        interface=IMMDeviceEnumerator,
    )
    device = enumerator.GetDefaultAudioEndpoint(0, 0)
    interface = device.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    volume = cast(interface, POINTER(IAudioEndpointVolume))
    volume.SetMasterVolumeLevelScalar(percent / 100.0, None)


def _set_windows_media_key_volume(percent: int) -> None:
    for _ in range(50):
        _press_key(VK_VOLUME_DOWN)
        time.sleep(0.002)
    for _ in range(round(percent / 2)):
        _press_key(VK_VOLUME_UP)
        time.sleep(0.002)


def _press_key(vk: int) -> None:
    ctypes.windll.user32.keybd_event(vk, 0, 0, 0)  # type: ignore[attr-defined]
    ctypes.windll.user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)  # type: ignore[attr-defined]
