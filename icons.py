"""
icons.py
Sidebar ve dashboard icin kucuk, tek renkli SVG ikonlar (Fluent/Material
tarzinda, cizgi tabanli - orijinal, basit geometriyle cizilmis; herhangi
bir ikon kutuphanesinden birebir kopyalanmamistir). Emoji karakterlerinin
(fontlara/isletim sistemine gore farkli gorunen, bazen kirpma/hizalama
sorunu yasanan) yerine gecerler.

Kullanim:
    from icons import get_icon
    btn.setIcon(get_icon("home", color="#a7a8b3", size=18))
    btn.setIconSize(QSize(18, 18))

QtSvg modulu bulunamazsa (bazi minimal PyQt5 kurulumlarinda ayri paket
olabiliyor), sessizce None doner - cagiran taraf bunu "ikon yok, sadece
metin goster" olarak degerlendirmeli (bkz. main.py'deki kullanim).
"""

from PyQt5.QtCore import QSize, QByteArray, Qt
from PyQt5.QtGui import QIcon, QPixmap, QPainter

try:
    from PyQt5.QtSvg import QSvgRenderer
    _SVG_AVAILABLE = True
except ImportError:
    _SVG_AVAILABLE = False


# Her ikon 24x24 viewBox'ta, cizgi (stroke) tabanli tanimlanmis.
# "{color}" yer tutucusu render sirasinda gercek renkle degistirilir.
_STROKE_ICONS = {
    "home": """
        <path d="M4 11 L12 4 L20 11" />
        <path d="M6 10 V20 H18 V10" />
        <rect x="10" y="14" width="4" height="6" />
    """,
    "gamepad": """
        <rect x="2" y="8" width="20" height="10" rx="5" />
        <line x1="7" y1="11" x2="7" y2="15" />
        <line x1="5" y1="13" x2="9" y2="13" />
        <circle cx="16" cy="11" r="1" fill="{color}" />
        <circle cx="18.2" cy="14" r="1" fill="{color}" />
    """,
    "settings": """
        <circle cx="12" cy="12" r="3" />
        <line x1="12" y1="2" x2="12" y2="5" />
        <line x1="12" y1="19" x2="12" y2="22" />
        <line x1="2" y1="12" x2="5" y2="12" />
        <line x1="19" y1="12" x2="22" y2="12" />
        <line x1="4.9" y1="4.9" x2="7" y2="7" />
        <line x1="17" y1="17" x2="19.1" y2="19.1" />
        <line x1="19.1" y1="4.9" x2="17" y2="7" />
        <line x1="7" y1="17" x2="4.9" y2="19.1" />
    """,
    "folder": """
        <path d="M3 6 H9 L11 8 H21 V19 H3 Z" />
    """,
    "refresh": """
        <path d="M4 12 a8 8 0 0 1 14-5.3" />
        <path d="M20 12 a8 8 0 0 1-14 5.3" />
        <polyline points="18 3 18 7 14 7" />
        <polyline points="6 21 6 17 10 17" />
    """,
    "grid": """
        <rect x="3" y="3" width="8" height="8" rx="1.5" />
        <rect x="13" y="3" width="8" height="8" rx="1.5" />
        <rect x="3" y="13" width="8" height="8" rx="1.5" />
        <rect x="13" y="13" width="8" height="8" rx="1.5" />
    """,
    "search": """
        <circle cx="10.5" cy="10.5" r="6.5" />
        <line x1="15.3" y1="15.3" x2="21" y2="21" />
    """,
    "help": """
        <circle cx="12" cy="12" r="9" />
        <path d="M9.2 9.3 a2.8 2.6 0 1 1 4.4 2.1 c-1 .7 -1.6 1.3 -1.6 2.4" />
        <line x1="12" y1="17.2" x2="12" y2="17.2" />
    """,
    "bell": """
        <path d="M6 10.5 a6 6 0 0 1 12 0 c0 4 1.5 5.5 1.5 5.5 H4.5 s1.5 -1.5 1.5 -5.5" />
        <path d="M10 19 a2 2 0 0 0 4 0" />
    """,
    "chevron-left": """
        <polyline points="15 4 7 12 15 20" />
    """,
    "chevron-right": """
        <polyline points="9 4 17 12 9 20" />
    """,
    "clock": """
        <circle cx="12" cy="12" r="9" />
        <polyline points="12 7 12 12 16 14" />
    """,
    "target": """
        <circle cx="12" cy="12" r="8.5" />
        <circle cx="12" cy="12" r="4.5" />
        <circle cx="12" cy="12" r="0.6" fill="{color}" />
    """,
    "shield": """
        <path d="M12 3 L19 6 V11 c0 5 -3.2 8 -7 9 c-3.8 -1 -7 -4 -7 -9 V6 Z" />
    """,
}

# Dolu (fill) ikonlar - tek parca sekil.
_FILL_ICONS = {
    "bolt": """<path d="M13 2 L4 14 H11 L10 22 L20 9 H13 Z" />""",
    "sparkle": """<path d="M12 2 L14 9 L21 11 L14 13 L12 20 L10 13 L3 11 L10 9 Z" />""",
    "circle": """<circle cx="12" cy="12" r="9" />""",
    "play": """<path d="M6 4 L20 12 L6 20 Z" />""",
}

_ICON_CACHE = {}


def _build_svg(name: str, color: str) -> str:
    if name in _STROKE_ICONS:
        body = _STROKE_ICONS[name].format(color=color)
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
            f'fill="none" stroke="{color}" stroke-width="2" '
            'stroke-linecap="round" stroke-linejoin="round">'
            f'{body}</svg>'
        )
    if name in _FILL_ICONS:
        body = _FILL_ICONS[name].format(color=color)
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
            f'fill="{color}">{body}</svg>'
        )
    raise KeyError(f"Bilinmeyen ikon: {name}")


def get_pixmap(name: str, color: str = "#e8e8ea", size: int = 20) -> "QPixmap | None":
    """Ikonu verilen renk/boyutla QPixmap olarak dondurur. QtSvg yoksa None."""
    if not _SVG_AVAILABLE:
        return None
    cache_key = (name, color, size)
    if cache_key in _ICON_CACHE:
        return _ICON_CACHE[cache_key]
    try:
        svg_str = _build_svg(name, color)
    except KeyError:
        return None
    renderer = QSvgRenderer(QByteArray(svg_str.encode("utf-8")))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    _ICON_CACHE[cache_key] = pixmap
    return pixmap


def get_icon(name: str, color: str = "#e8e8ea", size: int = 20) -> QIcon:
    """Ikonu QIcon olarak dondurur (QPushButton.setIcon icin). Ikon
    olusturulamazsa bos bir QIcon doner - buton sadece metnini gosterir,
    programi bozmaz."""
    pixmap = get_pixmap(name, color, size)
    if pixmap is None:
        return QIcon()
    return QIcon(pixmap)
