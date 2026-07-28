"""
title_bar.py
WeMod/Wand tarzinda ozel (native olmayan) baslik cubugu.

Windows'un varsayilan pencere cercevesi/baslik cubugu, koyu temali
uygulamalarda sistem temasina gore acik renkte kalabiliyor ve icerikle
arasinda ince, uyumsuz bir cizgi/kenarlik olusabiliyor (bkz. eski
ekran goruntusundeki ust kisimdaki bozuk cizgi). Bunu kokten cozmek
icin native baslik cubugu tamamen kaldirilir (FramelessWindowHint) ve
yerine uygulamanin kendi temasiyla birebir uyumlu, surukleme +
kucult/buyut/kapat destekli bu widget kullanilir.
"""

from PyQt5.QtCore import Qt, QSize
from PyQt5.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton


class CustomTitleBar(QWidget):
    """Sadece gorsel bir bar degil - pencereyi surukleme, cift tikla
    buyut/geri-yukle ve min/maks/kapat butonlarinin tum mantigini da
    yonetir. `window` parametresi, uzerinde islem yapilacak QMainWindow."""

    HEIGHT = 40

    def __init__(self, window, title: str, icon_pixmap=None, parent=None):
        super().__init__(parent)
        self.window_ref = window
        self.setObjectName("CustomTitleBar")
        self.setFixedHeight(self.HEIGHT)
        self._drag_pos = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 0, 8, 0)
        layout.setSpacing(8)

        if icon_pixmap is not None:
            icon_lbl = QLabel()
            icon_lbl.setObjectName("TitleBarIcon")
            icon_lbl.setPixmap(icon_pixmap)
            layout.addWidget(icon_lbl)

        self.title_lbl = QLabel(title)
        self.title_lbl.setObjectName("TitleBarText")
        layout.addWidget(self.title_lbl)
        layout.addStretch(1)

        self.min_btn = self._make_btn("\u2013", "Kucult")
        self.max_btn = self._make_btn("\u25A1", "Buyut / Geri Yukle")
        self.close_btn = self._make_btn("\u2715", "Kapat")
        self.close_btn.setObjectName("TitleBarCloseButton")

        self.min_btn.clicked.connect(self.window_ref.showMinimized)
        self.max_btn.clicked.connect(self._toggle_max_restore)
        self.close_btn.clicked.connect(self.window_ref.close)

        layout.addWidget(self.min_btn)
        layout.addWidget(self.max_btn)
        layout.addWidget(self.close_btn)

    def _make_btn(self, text: str, tooltip: str) -> QPushButton:
        btn = QPushButton(text)
        btn.setObjectName("TitleBarButton")
        btn.setFixedSize(44, self.HEIGHT)
        btn.setToolTip(tooltip)
        btn.setCursor(Qt.PointingHandCursor)
        return btn

    def _toggle_max_restore(self):
        if self.window_ref.isMaximized():
            self.window_ref.showNormal()
            self.max_btn.setText("\u25A1")
        else:
            self.window_ref.showMaximized()
            self.max_btn.setText("\u25A6")

    def set_title(self, text: str):
        self.title_lbl.setText(text)

    def sync_max_icon(self):
        """Disaridan (ör. cift tikla baslik cubugu disi bir yerden
        maksimize edilirse) buton ikonunu guncel duruma getirir."""
        self.max_btn.setText("\u25A6" if self.window_ref.isMaximized() else "\u25A1")

    # ---- Surukleme / cift tik ----
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPos() - self.window_ref.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and event.buttons() == Qt.LeftButton:
            if self.window_ref.isMaximized():
                # Buyutulmusken cubuktan tutup surukleyince once normal
                # boyuta don (WeMod/Windows'un standart davranisi).
                self.window_ref.showNormal()
                self.max_btn.setText("\u25A1")
                self._drag_pos = event.globalPos() - self.window_ref.frameGeometry().topLeft()
            self.window_ref.move(event.globalPos() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_pos = None

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._toggle_max_restore()
