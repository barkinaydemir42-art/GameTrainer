"""
toast.py
WeMod/Wand tarzi kisa omurlu bildirim ("toast"). Onemli olaylarda
(freeze uygulandi, yama yapildi, guncelleme var vb.) sadece durum
cubugunda/log panelinde sessizce kaybolmasin diye, pencerenin sag-alt
kosesinde belirip birkac saniye sonra kendiliginden kaybolan kucuk bir
kart gosterir.

Kullanim:
    from toast import show_toast
    show_toast(self, "Deger dondu: 100", kind="success")

`self` (ana pencere) parent olarak verilir; toast onun uzerinde (child
widget olarak) konumlanir, boylece pencere tasindiginda/boyutu
degistiginde de dogru yerde kalir.
"""

from PyQt5.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QPoint
from PyQt5.QtWidgets import QLabel, QGraphicsOpacityEffect

_ACCENTS = {
    "info": "#7c5cff",
    "success": "#43a047",
    "warning": "#ffa63d",
    "error": "#e5484d",
}

_ICONS = {
    "info": "\u2139",       # ℹ
    "success": "\u2713",    # ✓
    "warning": "\u26A0",    # ⚠
    "error": "\u2715",      # ✕
}

# Ayni pencere uzerinde ust uste binmesinler diye, o pencereye ait
# aktif toast'lari takip ediyoruz (parent id -> widget listesi).
_active = {}


def show_toast(parent_window, message: str, kind: str = "info", duration_ms: int = 3200):
    """parent_window uzerinde bir toast gosterir. kind: info/success/warning/error."""
    accent = _ACCENTS.get(kind, _ACCENTS["info"])
    icon = _ICONS.get(kind, _ICONS["info"])

    toast = QLabel(f"  {icon}   {message}  ", parent_window)
    toast.setObjectName("ToastLabel")
    toast.setWordWrap(False)
    toast.setStyleSheet(f"""
        QLabel#ToastLabel {{
            background-color: #1c1d24;
            color: #ffffff;
            border: 1px solid {accent};
            border-left: 4px solid {accent};
            border-radius: 8px;
            padding: 10px 16px;
            font-size: 12px;
            font-weight: 600;
        }}
    """)
    toast.adjustSize()
    toast.setMinimumHeight(38)

    key = id(parent_window)
    stack = _active.setdefault(key, [])

    def _reposition():
        margin = 20
        x = parent_window.width() - toast.width() - margin
        # Var olan diger toast'larin ustune yigilsin (en yeni en altta).
        y = parent_window.height() - margin - toast.height()
        for other in stack:
            if other is not toast and other.isVisible():
                y -= (other.height() + 10)
        return QPoint(max(0, x), max(0, y))

    toast.move(_reposition())
    toast.show()
    toast.raise_()
    stack.append(toast)

    opacity_effect = QGraphicsOpacityEffect(toast)
    toast.setGraphicsEffect(opacity_effect)
    opacity_effect.setOpacity(0.0)

    fade_in = QPropertyAnimation(opacity_effect, b"opacity", toast)
    fade_in.setDuration(180)
    fade_in.setStartValue(0.0)
    fade_in.setEndValue(1.0)
    fade_in.setEasingCurve(QEasingCurve.OutCubic)
    fade_in.start()
    toast._fade_in_anim = fade_in  # referansi canli tut (GC engelle)

    def _dismiss():
        fade_out = QPropertyAnimation(opacity_effect, b"opacity", toast)
        fade_out.setDuration(220)
        fade_out.setStartValue(1.0)
        fade_out.setEndValue(0.0)
        fade_out.setEasingCurve(QEasingCurve.InCubic)

        def _cleanup():
            if toast in stack:
                stack.remove(toast)
            toast.deleteLater()

        fade_out.finished.connect(_cleanup)
        fade_out.start()
        toast._fade_out_anim = fade_out

    timer = QTimer(toast)
    timer.setSingleShot(True)
    timer.timeout.connect(_dismiss)
    timer.start(duration_ms)
