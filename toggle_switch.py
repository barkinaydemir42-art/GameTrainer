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

from PyQt5.QtWidgets import QAbstractButton, QSizePolicy
from PyQt5.QtCore import Qt, QSize, QPropertyAnimation, QEasingCurve, pyqtProperty
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

        self.setFixedSize(self.sizeHint())
        self.toggled.connect(self._animate_to_state)

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
