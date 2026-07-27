"""
toggle_switch.py - WeMod/EA Wand tarzi animasyonlu "pill" toggle switch.

Freeze Manager tablosundaki kucuk QCheckBox yerine kullanilir: yuvarlak,
kayan topu olan, acik/kapali renk gecisli bir anahtar. Davranis olarak
QAbstractButton'dan turer (checkable=True) - toggled(bool) sinyali verir,
setChecked()/isChecked() ile QCheckBox gibi kullanilabilir, bu yuzden
mevcut main.py kodunda checkbox'i degistirmek tek satirlik bir islem.

WeMod'daki gibi: kapaliyken gri/koyu gri, aciliken canli yesil, top
sola/saga yumusak animasyonla kayar.
"""

from PyQt5.QtWidgets import QAbstractButton, QSizePolicy, QGraphicsDropShadowEffect
from PyQt5.QtCore import (
    Qt, QSize, QPropertyAnimation, QEasingCurve, pyqtProperty,
    QSequentialAnimationGroup,
)
from PyQt5.QtGui import QPainter, QColor, QPen


class ToggleSwitch(QAbstractButton):
    """Animasyonlu acik/kapali anahtar. QCheckBox yerine drop-in kullanilir."""

    def __init__(self, parent=None, on_color="#43a047", off_color="#555555",
                 knob_color="#ffffff", width=44, height=22):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self._on_color = QColor(on_color)
        self._off_color = QColor(off_color)
        self._knob_color = QColor(knob_color)
        self._track_w = width
        self._track_h = height
        self._knob_margin = 2
        self._knob_d = height - 2 * self._knob_margin

        # 0.0 = tamamen kapali (topun sol konumu), 1.0 = tamamen acik (sag konum)
        self._offset = 0.0

        self._anim = QPropertyAnimation(self, b"offset", self)
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.InOutCubic)

        # ---- Hover/glow efekti (WeMod tarzi) ----
        # QGraphicsDropShadowEffect'i offset=(0,0) ile kullanmak, ozunde
        # widget'in etrafina yumusak/bulanik bir "hale" (glow) cizer.
        # blurRadius'u QPropertyAnimation ile 0'dan bir hedefe animasyonla
        # artirip azaltarak, fareyle uzerine gelince/toggle acilinca
        # yumusak bir parlama efekti elde ediyoruz.
        self._glow = QGraphicsDropShadowEffect(self)
        self._glow.setOffset(0, 0)
        self._glow.setBlurRadius(0)
        self._glow.setColor(self._glow_color(self._off_color))
        self.setGraphicsEffect(self._glow)
        self._hovered = False

        self._hover_anim = QPropertyAnimation(self._glow, b"blurRadius", self)
        self._hover_anim.setDuration(180)
        self._hover_anim.setEasingCurve(QEasingCurve.OutCubic)

        # Toggle acildiginda kisa bir "pulse" (parla-sonra-sonumle) - iki
        # asamali oldugu icin QSequentialAnimationGroup kullanilir.
        self._pulse_group = QSequentialAnimationGroup(self)
        self._pulse_up = QPropertyAnimation(self._glow, b"blurRadius", self)
        self._pulse_up.setDuration(120)
        self._pulse_up.setEasingCurve(QEasingCurve.OutCubic)
        self._pulse_down = QPropertyAnimation(self._glow, b"blurRadius", self)
        self._pulse_down.setDuration(220)
        self._pulse_down.setEasingCurve(QEasingCurve.InOutCubic)
        self._pulse_group.addAnimation(self._pulse_up)
        self._pulse_group.addAnimation(self._pulse_down)

        self.setFixedSize(self.sizeHint())
        self.toggled.connect(self._animate_to_state)
        self.toggled.connect(self._animate_glow_toggle)

    def _glow_color(self, base: QColor) -> QColor:
        """Tam opak degil, yari saydam bir parlama rengi - aksi halde
        QGraphicsDropShadowEffect kati/sert bir hale gibi gorunur."""
        c = QColor(base)
        c.setAlpha(190)
        return c

    # --- offset Qt property (QPropertyAnimation bunun uzerinden calisir) ---
    def _get_offset(self):
        return self._offset

    def _set_offset(self, value):
        self._offset = value
        self.update()

    offset = pyqtProperty(float, _get_offset, _set_offset)

    def _animate_to_state(self, checked: bool):
        self._anim.stop()
        self._anim.setStartValue(self._offset)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def _hover_target_blur(self) -> float:
        """Fareyle uzerine gelindiginde ulasilacak parlama (blur) miktari.
        Acikken (yesil/checked) biraz daha guclu parlar, kapaliyken hafif."""
        if not self.isEnabled():
            return 0.0
        return 20.0 if self.isChecked() else 10.0

    def _start_hover_anim(self, target: float):
        self._pulse_group.stop()
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._glow.blurRadius())
        self._hover_anim.setEndValue(target)
        self._hover_anim.start()

    def enterEvent(self, event):
        self._hovered = True
        self._start_hover_anim(self._hover_target_blur())
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self._start_hover_anim(0.0)
        super().leaveEvent(event)

    def _animate_glow_toggle(self, checked: bool):
        """Anahtar acilip kapandiginda parlama rengini gunceller ve -
        sadece acilirken - kisa bir 'pulse' (parla-sonup-git) efekti
        oynatir. WeMod'daki gibi acilis anini gorsel olarak vurgular."""
        self._glow.setColor(self._glow_color(self._on_color if checked else self._off_color))
        if not self.isEnabled():
            return
        settle_target = self._hover_target_blur() if self._hovered else 0.0
        if checked:
            self._hover_anim.stop()
            self._pulse_group.stop()
            self._pulse_up.setStartValue(self._glow.blurRadius())
            self._pulse_up.setEndValue(28.0)
            self._pulse_down.setStartValue(28.0)
            self._pulse_down.setEndValue(settle_target)
            self._pulse_group.start()
        else:
            self._start_hover_anim(settle_target)

    def setEnabled(self, enabled: bool):
        super().setEnabled(enabled)
        if not enabled:
            self._pulse_group.stop()
            self._hover_anim.stop()
            self._glow.setBlurRadius(0)

    def setChecked(self, checked: bool):
        # Programatik setChecked() cagrildiginda da (profil yuklerken,
        # tablo yeniden cizilirken vb.) animasyon dogru konuma gitsin -
        # ama satir yeniden olusturulurken sicradigi icin ilk deger
        # animasyonsuz set edilir (bkz. set_checked_instant).
        super().setChecked(checked)

    def set_checked_instant(self, checked: bool):
        """Tabloyu yeniden cizerken (satir yeniden olusuyor) animasyon
        oynatmadan doğru konumu ayarlar - aksi halde her _refresh_freeze_table()
        cagrisinda tum toggle'lar bastan animasyon oynatirdi."""
        self.blockSignals(True)
        self.setChecked(checked)
        self.blockSignals(False)
        self._offset = 1.0 if checked else 0.0
        self._glow.setColor(self._glow_color(self._on_color if checked else self._off_color))
        self.update()

    def sizeHint(self):
        return QSize(self._track_w, self._track_h)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)

        # Track (arka plan pill) - kapali griden acik yesile yumusak gecis
        track_color = QColor(
            int(self._off_color.red() + (self._on_color.red() - self._off_color.red()) * self._offset),
            int(self._off_color.green() + (self._on_color.green() - self._off_color.green()) * self._offset),
            int(self._off_color.blue() + (self._on_color.blue() - self._off_color.blue()) * self._offset),
        )
        painter.setBrush(track_color)
        painter.drawRoundedRect(0, 0, self._track_w, self._track_h, self._track_h / 2, self._track_h / 2)

        # Devre disi (attach yokken) hafif saydamlik
        if not self.isEnabled():
            painter.setOpacity(0.45)

        # Knob (kayan top)
        x_min = self._knob_margin
        x_max = self._track_w - self._knob_margin - self._knob_d
        knob_x = x_min + (x_max - x_min) * self._offset
        painter.setBrush(self._knob_color)
        painter.drawEllipse(int(knob_x), self._knob_margin, self._knob_d, self._knob_d)
        painter.end()

    def hitButton(self, pos):
        return self.rect().contains(pos)
