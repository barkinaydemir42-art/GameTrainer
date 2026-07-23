"""
modern_theme.py - LocalTrainer Studio icin modern arayuz temasi

KULLANIM:
main.py icindeki mevcut `apply_theme` metodunu SIL, yerine bunu koy:

    from modern_theme import apply_theme
    ...
    self.apply_theme = lambda: apply_theme(self)

ya da daha basiti: main.py'de `def apply_theme(self):` fonksiyonunun
GOVDESINI asagidaki MODERN_QSS ile degistir (sadece
`self.setStyleSheet(MODERN_QSS)` yaz).

Bu tema:
- Duz (flat), koseleri yuvarlatilmis, "glass" hissi veren koyu tema
- Vurgu rengi: mor-mavi gradient (istersen ACCENT degiskenini degistir)
- Sekmeler (QTabWidget) modern pill/segment gorunumu
- Butonlarda hover/pressed animasyon hissi (gercek animasyon degil,
  renk gecisi - PyQt5 QSS gercek CSS transition desteklemiyor)
- Tablo/liste satirlari daha ferah (padding artti), secili satir vurgulu
"""

ACCENT = "#7C5CFF"       # ana vurgu rengi (mor)
ACCENT_HOVER = "#9277FF"
ACCENT_PRESSED = "#6A4CE0"
BG_MAIN = "#14151A"
BG_PANEL = "#1C1E26"
BG_INPUT = "#22242E"
BORDER = "#2E3140"
TEXT = "#E8E8ED"
TEXT_DIM = "#9A9CB0"
DANGER = "#E5484D"

MODERN_QSS = f"""
QMainWindow, QWidget {{
    background-color: {BG_MAIN};
    color: {TEXT};
    font-family: "Segoe UI", "Inter", sans-serif;
    font-size: 13px;
}}

QDockWidget {{
    color: {TEXT_DIM};
    font-weight: 600;
}}
QDockWidget::title {{
    background: {BG_PANEL};
    padding: 6px 10px;
    border-bottom: 1px solid {BORDER};
}}

/* ---- Sekmeler (ust seviye ve alt seviye) ---- */
QTabWidget::pane {{
    border: 1px solid {BORDER};
    border-radius: 10px;
    background: {BG_PANEL};
    top: -1px;
}}
QTabBar::tab {{
    background: transparent;
    color: {TEXT_DIM};
    padding: 8px 18px;
    margin: 4px 3px;
    border-radius: 8px;
    font-weight: 500;
}}
QTabBar::tab:selected {{
    background: {ACCENT};
    color: white;
}}
QTabBar::tab:hover:!selected {{
    background: {BG_INPUT};
    color: {TEXT};
}}

/* ---- Butonlar ---- */
QPushButton {{
    background: {BG_INPUT};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 8px 14px;
    font-weight: 500;
}}
QPushButton:hover {{
    background: {ACCENT_HOVER};
    border-color: {ACCENT_HOVER};
    color: white;
}}
QPushButton:pressed {{
    background: {ACCENT_PRESSED};
}}
QPushButton:disabled {{
    color: #55576A;
    background: {BG_PANEL};
}}

/* ---- Girdi alanlari ---- */
QLineEdit, QComboBox, QTextEdit, QListWidget, QTableWidget, QSpinBox {{
    background: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 6px 8px;
    selection-background-color: {ACCENT};
}}
QLineEdit:focus, QComboBox:focus {{
    border: 1px solid {ACCENT};
}}
QComboBox::drop-down {{
    border: none;
    width: 22px;
}}

/* ---- Tablo basliklari ---- */
QHeaderView::section {{
    background: {BG_PANEL};
    color: {TEXT_DIM};
    padding: 6px;
    border: none;
    border-bottom: 1px solid {BORDER};
    font-weight: 600;
}}
QTableWidget {{
    gridline-color: {BORDER};
    alternate-background-color: {BG_PANEL};
}}
QTableWidget::item:selected {{
    background: {ACCENT};
    color: white;
}}

/* ---- Grup kutulari ---- */
QGroupBox {{
    border: 1px solid {BORDER};
    border-radius: 10px;
    margin-top: 14px;
    padding-top: 10px;
    font-weight: 600;
    color: {TEXT_DIM};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: {TEXT};
}}

/* ---- Kaydirma cubuklari ---- */
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
}}
QScrollBar::handle:vertical {{
    background: {BORDER};
    border-radius: 5px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{
    background: {ACCENT};
}}

/* ---- Durum cubugu ---- */
QStatusBar {{
    background: {BG_PANEL};
    color: {TEXT_DIM};
    border-top: 1px solid {BORDER};
}}

/* ---- Onay kutulari ---- */
QCheckBox {{
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 1px solid {BORDER};
    background: {BG_INPUT};
}}
QCheckBox::indicator:checked {{
    background: {ACCENT};
    border-color: {ACCENT};
}}
"""

# "Tehlike" butonlari icin (Tumunu Sil, Detach, Geri Al vb.)
DANGER_BUTTON_QSS = f"background-color: {DANGER}; color: white; border-radius: 8px; padding: 8px 14px; font-weight: 600;"

# "Basarili/Onayla" butonlari icin (ornegin Guncelle butonu)
SUCCESS = "#3DDC84"
SUCCESS_BUTTON_QSS = f"background-color: {SUCCESS}; color: #0B1F13; border-radius: 8px; padding: 8px 14px; font-weight: 600;"


def apply_theme(main_window):
    """main.py icindeki LocalTrainerStudio.apply_theme metodunun yerini alir."""
    main_window.setStyleSheet(MODERN_QSS)
