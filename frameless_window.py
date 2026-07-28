"""
frameless_window.py
FramelessWindowHint kullanan pencereler icin Windows'a ozel yardimcilar:

1) Kenarlardan/koselerden fare ile yeniden boyutlandirma (native
   baslik cubugu olmadan Qt bunu kendiliginden vermez).
2) DWM govde golgesi - cerceve olmasa da pencereye ince, dogal bir
   golge ekler (WeMod/Wand gibi uygulamalarin "havada duruyor" hissi).
3) Windows 11'de yuvarlatilmis pencere koseleri (destekleyen surumlerde;
   Windows 10'da sessizce yok sayilir).

Tamami dener/basarisiz-olursa-sessizce-gec mantigiyla yazildi - Windows
disinda (ya da eksik DLL/eski surumde) uygulamayi asla cokertmez, sadece
o gorsel iyilestirmeyi atlar.
"""

import sys
import ctypes
from ctypes import wintypes

from PyQt5.QtCore import Qt, QPoint

_IS_WINDOWS = sys.platform.startswith("win")

_BORDER = 8  # px - fare ile yakalanabilecek kenar payi

# WM_NCHITTEST donus kodlari
_HT = {
    "left": 10, "right": 11, "top": 12, "bottom": 15,
    "topleft": 13, "topright": 14, "bottomleft": 16, "bottomright": 17,
    "caption": 2, "client": 1,
}


class MARGINS(ctypes.Structure):
    _fields_ = [
        ("cxLeftWidth", ctypes.c_int),
        ("cxRightWidth", ctypes.c_int),
        ("cyTopHeight", ctypes.c_int),
        ("cyBottomHeight", ctypes.c_int),
    ]


def enable_dwm_shadow(hwnd: int):
    """Frameless pencereye 1px'lik dogal DWM golgesi ekler."""
    if not _IS_WINDOWS:
        return
    try:
        margins = MARGINS(1, 1, 1, 1)
        ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea(
            wintypes.HWND(hwnd), ctypes.byref(margins)
        )
    except Exception:
        pass  # DWM devre disiysa (ör. eski/uzak masaustu) sessizce atla


def enable_rounded_corners(hwnd: int):
    """Windows 11 build 22000+ icin kose yuvarlatma tercihini bildirir."""
    if not _IS_WINDOWS:
        return
    try:
        DWMWA_WINDOW_CORNER_PREFERENCE = 33
        DWMWCP_ROUND = 2
        value = ctypes.c_int(DWMWCP_ROUND)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            wintypes.HWND(hwnd),
            ctypes.c_int(DWMWA_WINDOW_CORNER_PREFERENCE),
            ctypes.byref(value),
            ctypes.sizeof(value),
        )
    except Exception:
        pass  # Windows 10 veya daha eskisinde bu ozellik yok - sorun degil


class FramelessResizeMixin:
    """QMainWindow alt sinifina karistirilir (mixin). Kenarlardan
    surukleyerek boyutlandirmayi WM_NCHITTEST'i yanitlayarak isletim
    sistemine devrettigi icin fare imleci de otomatik dogru gorunur
    (ok yerine <-> / resize imleci)."""

    def nativeEvent(self, eventType, message):
        if _IS_WINDOWS and eventType == b"windows_generic_MSG":
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == 0x0084:  # WM_NCHITTEST
                if self.isMaximized() or self.isFullScreen():
                    return False, 0
                x = msg.lParam & 0xFFFF
                y = (msg.lParam >> 16) & 0xFFFF
                if x > 32767:
                    x -= 65536
                if y > 32767:
                    y -= 65536
                pos = self.mapFromGlobal(QPoint(x, y))
                w, h = self.width(), self.height()

                left = pos.x() <= _BORDER
                right = pos.x() >= w - _BORDER
                top = pos.y() <= _BORDER
                bottom = pos.y() >= h - _BORDER

                if top and left:
                    return True, _HT["topleft"]
                if top and right:
                    return True, _HT["topright"]
                if bottom and left:
                    return True, _HT["bottomleft"]
                if bottom and right:
                    return True, _HT["bottomright"]
                if left:
                    return True, _HT["left"]
                if right:
                    return True, _HT["right"]
                if top:
                    return True, _HT["top"]
                if bottom:
                    return True, _HT["bottom"]
        return super().nativeEvent(eventType, message)
