"""
themes.py
Uygulama genelinde kullanilan tum renkler burada TEK YERDE tanimlanir.
apply_theme() eskiden sabit hex kodlarla dolu tek bir stylesheet
uretiyordu - artik ayni stylesheet SABLONU, secilen temanin renk
paletiyle doldurularak uretiliyor. Yeni bir tema eklemek icin asagidaki
THEMES sozlugune yeni bir palet eklemek yeterli (baska hicbir yer
degismez).
"""

# Her palet, orijinal (tek) stylesheet'te kullanilan HER rengi karsilar.
# Anahtar isimleri renklerin STYLESHEET'TEKI ROLUNU anlatir (renk adini
# degil) - boylece "accent" gibi bir anahtar temaya gore mor/mavi/turuncu
# olabilir ama anlami (vurgu rengi) hep ayni kalir.
THEMES = {
    "dark": {
        "window_bg": "#14151a",
        "text": "#e8e8ea",
        "sidebar_bg": "#191a20",
        "border": "#2a2b33",
        "surface": "#1f2027",       # brand/tab/input/header arka planlari
        "text_dim": "#a7a8b3",      # nav buton yazisi
        "hover_bg": "#23242c",
        "checked_bg": "#23252f",
        "text_faint": "#55565f",    # versiyon etiketi
        "text_muted": "#9092a0",    # alt baslik, tab yazisi
        "text_soft": "#c8c9d6",     # kart basligi
        "card_bg": "#1c1d24",
        "pane_bg": "#1a1b21",
        "table_bg": "#16171d",
        "input_border": "#34353f",
        "accent": "#7c5cff",
        "accent_soft": "#a794ff",   # groupbox basligi (daha acik vurgu)
        "accent_hover": "#9177ff",
        "accent_pressed": "#6748e0",
    },
    "oled": {
        # Gercek siyah (#000000) arka planlar - OLED ekranlarda piksel
        # kapatip enerji tasarrufu saglar, ayrica gece kullanimda goz
        # yormaz. Vurgu rengi Dark ile ayni (mor) birakildi.
        "window_bg": "#000000",
        "text": "#e8e8ea",
        "sidebar_bg": "#000000",
        "border": "#1c1c1c",
        "surface": "#0c0c0e",
        "text_dim": "#8a8b94",
        "hover_bg": "#141416",
        "checked_bg": "#101012",
        "text_faint": "#4a4a52",
        "text_muted": "#84858f",
        "text_soft": "#b8b9c4",
        "card_bg": "#060607",
        "pane_bg": "#000000",
        "table_bg": "#000000",
        "input_border": "#2a2a2e",
        "accent": "#7c5cff",
        "accent_soft": "#a794ff",
        "accent_hover": "#9177ff",
        "accent_pressed": "#6748e0",
    },
    "blue": {
        # Mavi vurgulu, hafif mavi tonlu koyu gri arka planlar.
        "window_bg": "#12161d",
        "text": "#e6ebf3",
        "sidebar_bg": "#161b24",
        "border": "#26303f",
        "surface": "#1b222d",
        "text_dim": "#9aa7ba",
        "hover_bg": "#212a37",
        "checked_bg": "#1e2836",
        "text_faint": "#5b6675",
        "text_muted": "#8b98aa",
        "text_soft": "#c3ccd9",
        "card_bg": "#181f29",
        "pane_bg": "#161c25",
        "table_bg": "#141922",
        "input_border": "#31404f",
        "accent": "#2f7bff",
        "accent_soft": "#7fadff",
        "accent_hover": "#5590ff",
        "accent_pressed": "#1f5fd6",
    },
    "orange": {
        # Turuncu vurgulu, notr/sicak koyu gri arka planlar.
        "window_bg": "#17140f",
        "text": "#f0e9e0",
        "sidebar_bg": "#1b1712",
        "border": "#332a1f",
        "surface": "#221c14",
        "text_dim": "#b3a692",
        "hover_bg": "#2a2318",
        "checked_bg": "#2a2117",
        "text_faint": "#6b5f4d",
        "text_muted": "#a89a84",
        "text_soft": "#d9cbb5",
        "card_bg": "#1f1a13",
        "pane_bg": "#1c170f",
        "table_bg": "#191510",
        "input_border": "#3d3120",
        "accent": "#ff8a3d",
        "accent_soft": "#ffb27a",
        "accent_hover": "#ffa15f",
        "accent_pressed": "#e06f22",
    },
}

THEME_LABELS = {
    "dark": "Karanlik (Varsayilan)",
    "oled": "OLED (Saf Siyah)",
    "blue": "Mavi",
    "orange": "Turuncu",
}

DEFAULT_THEME = "dark"

_STYLESHEET_TEMPLATE = """
    QMainWindow, QWidget {{
        background-color: {window_bg};
        color: {text};
        font-family: 'Segoe UI';
        font-size: 13px;
    }}

    /* ---- Sol menu (sidebar) ---- */
    #Sidebar {{ background-color: {sidebar_bg}; border-right: 1px solid {border}; }}
    #Brand {{
        font-size: 15px; font-weight: bold; color: #ffffff;
        background-color: {surface}; border-bottom: 1px solid {border};
    }}
    #NavButton {{
        text-align: left; background-color: transparent; color: {text_dim};
        border: none; border-radius: 0px; padding: 12px 18px;
        font-weight: 600; margin: 0px;
    }}
    #NavButton:hover {{ background-color: {hover_bg}; color: #ffffff; }}
    #NavButton:checked {{
        background-color: {checked_bg}; color: #ffffff;
        border-left: 3px solid {accent};
    }}
    #VersionLabel {{ color: {text_faint}; font-size: 11px; padding: 10px; }}

    /* ---- Dashboard ---- */
    #PageTitle {{ font-size: 22px; font-weight: bold; color: #ffffff; }}
    #PageSubtitle {{ color: {text_muted}; font-size: 13px; }}
    #Card {{
        background-color: {card_bg}; border: 1px solid {border};
        border-radius: 10px; padding: 16px;
    }}
    #CardHeader {{ font-size: 14px; font-weight: bold; color: {text_soft}; }}
    #DashStatus {{ font-size: 15px; font-weight: 600; color: #ffffff; padding-bottom: 8px; }}

    /* ---- Sekmeler (tabs) ---- */
    QTabWidget::pane {{ border: 1px solid {border}; background-color: {pane_bg}; border-radius: 6px; }}
    QTabBar::tab {{
        background-color: {surface}; color: {text_muted}; padding: 8px 18px;
        margin-right: 3px; border-top-left-radius: 6px; border-top-right-radius: 6px;
    }}
    QTabBar::tab:selected {{ background-color: {accent}; color: #ffffff; font-weight: bold; }}
    QTabBar::tab:hover {{ background-color: {border}; color: #ffffff; }}

    QTableWidget, QTextEdit, QListWidget {{
        background-color: {table_bg}; color: #ffffff;
        border: 1px solid {border}; border-radius: 6px; gridline-color: {border};
    }}
    QHeaderView::section {{
        background-color: {surface}; color: #ffffff; padding: 6px;
        border: 1px solid {border}; font-weight: bold;
    }}
    QPushButton {{
        background-color: {accent}; color: white; border-radius: 6px;
        padding: 7px 16px; font-weight: 600; border: none;
    }}
    QPushButton:hover {{ background-color: {accent_hover}; }}
    QPushButton:pressed {{ background-color: {accent_pressed}; }}
    QLineEdit, QComboBox {{
        background-color: {surface}; border: 1px solid {input_border};
        padding: 6px; color: white; border-radius: 5px;
    }}
    QLineEdit:focus, QComboBox:focus {{ border: 1px solid {accent}; }}
    QGroupBox {{
        border: 1px solid {border}; margin-top: 15px; font-weight: bold;
        color: {accent_soft}; border-radius: 6px; padding-top: 10px;
    }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 5px; }}
    QListWidget::item {{ padding: 6px; border-radius: 4px; }}
    QListWidget::item:selected {{ background-color: {accent}; color: white; }}
    QStatusBar {{ background-color: {accent}; color: white; font-weight: bold; }}
    QProgressBar {{
        background-color: {surface}; border: 1px solid {border};
        border-radius: 5px; text-align: center; color: white;
    }}
    QProgressBar::chunk {{ background-color: {accent}; border-radius: 5px; }}

    /* ---- Oyun Kutuphanesi kartlari ---- */
    #LibraryScroll {{ border: none; background: transparent; }}
    #GameCard {{
        background-color: {card_bg}; border: 1px solid {border};
        border-radius: 10px;
    }}
    #GameCard:hover {{ border: 1px solid {accent}; background-color: {hover_bg}; }}
    #GameCardCover {{ background-color: {surface}; border-radius: 6px; }}
    #GameCardTitle {{ color: #ffffff; font-weight: 600; font-size: 12px; }}
    #GameCardSource {{ color: {text_muted}; font-size: 11px; }}
"""


def build_stylesheet(theme_key: str) -> str:
    """Verilen tema anahtari icin tam Qt stylesheet stringini uretir.
    Bilinmeyen bir anahtar gelirse (ornek: eski/bozuk config dosyasi)
    sessizce varsayilan temaya duser - uygulama asla temasiz/crash
    olmus halde acilmaz."""
    palette = THEMES.get(theme_key, THEMES[DEFAULT_THEME])
    return _STYLESHEET_TEMPLATE.format(**palette)
