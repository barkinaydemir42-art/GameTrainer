"""
main.py - LocalTrainer Studio (Merged Edition)

Onceki PyQt5 arayuz tasarimi (koyu tema, Wizard/Scanner/Freeze/Patch/Script
sekmeleri) korunuyor, ama artik her buton gercekten calisiyor:
- Attach  -> memory_engine.MemoryEngine.attach()
- Scan    -> gercek bellek tarama (first/next scan)
- AOB     -> gercek pattern (wildcard) tarama
- Freeze  -> arka plan QTimer ile surekli deger yazma
- Patch   -> ham byte yazma + orijinali saklayip geri alma (undo)
- Script  -> kisitli, guvenli mini komut dili (eval/exec KULLANILMAZ)

SADECE WINDOWS'ta calisir (ReadProcessMemory/WriteProcessMemory).
"""

import sys
import os
import json
import multiprocessing
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QGridLayout, QTabWidget, QPushButton, QLabel,
    QLineEdit, QComboBox, QTableWidget, QTableWidgetItem,
    QTextEdit, QStatusBar, QDockWidget,
    QMessageBox, QListWidget, QGroupBox, QSplitter, QStackedWidget,
    QFileDialog, QInputDialog, QCheckBox, QHeaderView, QListWidgetItem,
    QProgressBar, QButtonGroup, QFrame, QSizePolicy, QAbstractItemView,
    QScrollArea
)
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal, QSize
from PyQt5.QtGui import QPixmap, QPainter

from memory_engine import (
    MemoryEngine, WatchedAddress, list_processes, list_processes_with_windows, ALL_TYPES,
)
from profile_manager import save_profile, load_profile, profile_exists, list_profiles, PROFILES_DIR
from hotkeys import HotkeyManager
from script_engine import ScriptEngine, ScriptError
from toggle_switch import ToggleSwitch
from icons import get_icon, get_pixmap
from game_library import scan_all_libraries, get_cached_cover_path, download_cover
import updater
import config_manager
import themes
from app_paths import get_app_data_dir

REFRESH_MS = 500


class ScanWorker(QThread):
    """
    Herhangi bir agir MemoryEngine cagrisini (first_scan, next_scan,
    pattern_scan, find_pointers_to, vb.) arka planda calistirir.

    ONCEKI HATA: bu tarama fonksiyonlari dogrudan buton click handler'i
    icinde, ana arayuz (UI) thread'inde cagriliyordu. Buyuk oyunlarda
    (GB'larca bellek + ozellikle 2 seviyeli pointer scan icin onlarca
    tekrar tarama) bu islem uzun surdugunde, Qt'nin event loop'u pompalanamadigi
    icin Windows pencereyi "Yanit Vermiyor" olarak isaretliyordu - programin
    kendisi cokmuyordu ama kullaniciya cokmus gibi gorunuyordu. Artik TUM
    tarama cagrilari bu QThread uzerinden yapiliyor, ana pencere her zaman
    yanit veriyor.
    """
    finished_ok = pyqtSignal(object)
    finished_error = pyqtSignal(str)

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs

    def run(self):
        try:
            result = self.fn(*self.args, **self.kwargs)
            self.finished_ok.emit(result)
        except Exception as e:
            self.finished_error.emit(str(e))


class CoverFetchWorker(QThread):
    """Oyun kutuphanesi kartlari icin kapak gorsellerini arka planda
    indirir. AG cagrilari (download_cover) UI thread'inde yapilirsa
    arayuz her kapak icin kisa sureligine donar - bu yuzden tum liste
    burada, ayri bir thread'de sirayla indirilir. Her basarili indirmede
    cover_ready(index, path) yayinlanir, boylece kartlar hepsi bitmeden
    tek tek guncellenir (kullanici 50 oyunluk kutuphanenin tamamen
    inmesini beklemek zorunda kalmaz)."""
    cover_ready = pyqtSignal(int, str)
    finished_all = pyqtSignal()

    def __init__(self, games):
        super().__init__()
        self.games = games

    def run(self):
        for i, g in enumerate(self.games):
            try:
                path = download_cover(g)
            except Exception:
                path = None
            if path:
                self.cover_ready.emit(i, path)
        self.finished_all.emit()


class GameCard(QFrame):
    """Oyun Kutuphanesi sayfasindaki tek bir oyun karti (kapak + ad +
    kaynak rozeti). Cift tiklaninca activated sinyali ile index'ini
    bildirir - main.py bunu Trainer Wizard'a yonlendirmek icin kullanir."""
    activated = pyqtSignal(int)

    COVER_W, COVER_H = 120, 180  # Steam dikey kapak orani (2:3) ile uyumlu

    def __init__(self, index: int, game, parent=None):
        super().__init__(parent)
        self.index = index
        self.game = game
        self.setObjectName("GameCard")
        self.setAttribute(Qt.WA_Hover, True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedWidth(self.COVER_W + 24)

        v = QVBoxLayout(self)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(6)

        self.cover_label = QLabel()
        self.cover_label.setObjectName("GameCardCover")
        self.cover_label.setFixedSize(self.COVER_W, self.COVER_H)
        self.cover_label.setAlignment(Qt.AlignCenter)
        self._set_placeholder()
        v.addWidget(self.cover_label, 0, Qt.AlignHCenter)

        name_lbl = QLabel(game.name)
        name_lbl.setObjectName("GameCardTitle")
        name_lbl.setWordWrap(True)
        name_lbl.setAlignment(Qt.AlignCenter)
        v.addWidget(name_lbl)

        source_lbl = QLabel(game.source)
        source_lbl.setObjectName("GameCardSource")
        source_lbl.setAlignment(Qt.AlignCenter)
        v.addWidget(source_lbl)

        # Onbellekte zaten indirilmis bir kapak varsa (ag cagrisi
        # yapmadan) hemen goster - sadece yeni/ilk kez gorulen Steam
        # oyunlari icin arka plan indirmesi beklenir.
        cached = get_cached_cover_path(game)
        if cached:
            self.set_cover(cached)

    def _set_placeholder(self):
        """Kapak henuz yokken (indirilene kadar, ya da Steam disi bir
        kaynak oldugu icin hic olmayacaksa) gamepad ikonunu ortala."""
        pm = get_pixmap("gamepad", color="#55565f", size=48)
        canvas = QPixmap(self.COVER_W, self.COVER_H)
        canvas.fill(Qt.transparent)
        if pm is not None and not pm.isNull():
            painter = QPainter(canvas)
            x = (self.COVER_W - pm.width()) // 2
            y = (self.COVER_H - pm.height()) // 2
            painter.drawPixmap(x, y, pm)
            painter.end()
        self.cover_label.setPixmap(canvas)

    def set_cover(self, path: str):
        pm = QPixmap(path)
        if pm.isNull():
            return
        # Karti tamamen doldurup ortadan kirp - kapak tam 2:3 olmayabilir
        # (ozellikle yatay 'header' yedegi), boylece bosluk/deformasyon olmaz.
        scaled = pm.scaled(self.COVER_W, self.COVER_H, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        x = max(0, (scaled.width() - self.COVER_W) // 2)
        y = max(0, (scaled.height() - self.COVER_H) // 2)
        cropped = scaled.copy(x, y, self.COVER_W, self.COVER_H)
        self.cover_label.setPixmap(cropped)

    def mouseDoubleClickEvent(self, event):
        self.activated.emit(self.index)
        super().mouseDoubleClickEvent(event)


class UpdateCheckWorker(QThread):
    """Guncelleme kontrolunu ve indirmeyi arka planda (UI dondurmadan) yapar."""
    check_finished = pyqtSignal(object)   # UpdateInfo veya None
    check_error = pyqtSignal(str)
    download_progress = pyqtSignal(int, int)
    download_finished = pyqtSignal(str)   # indirilen dosya yolu
    download_error = pyqtSignal(str)

    def __init__(self, mode: str, manifest_url: str = "", update_info=None):
        super().__init__()
        self.mode = mode  # 'check' veya 'download'
        self.manifest_url = manifest_url
        self.update_info = update_info

    def run(self):
        if self.mode == "check":
            try:
                info = updater.check_for_update(self.manifest_url)
                self.check_finished.emit(info)
            except Exception as e:
                self.check_error.emit(str(e))
        elif self.mode == "download":
            try:
                path = updater.download_and_prepare_update(
                    self.update_info,
                    progress_cb=lambda d, t: self.download_progress.emit(d, t),
                )
                self.download_finished.emit(path)
            except Exception as e:
                self.download_error.emit(str(e))


class LocalTrainerStudio(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"LocalTrainer Studio v{updater.CURRENT_VERSION} - Merged Edition (Calisan Motor)")
        self.setGeometry(50, 50, 1250, 820)

        # ---- Gercek backend ----
        self.engine = MemoryEngine()
        self.hotkeys = HotkeyManager()
        self.script_engine = ScriptEngine(self.engine, on_log=self._log_safe)
        self.watched: list[WatchedAddress] = []
        self.current_game_label = ""
        self.byte_patches: dict[int, bytes] = {}  # address -> orijinal bytelar (undo icin)

        # ---- Guncelleme durumu ----
        self.app_config = config_manager.load_config()
        self.current_theme = self.app_config.get("theme", themes.DEFAULT_THEME)
        if self.current_theme not in themes.THEMES:
            self.current_theme = themes.DEFAULT_THEME
        self.pending_update = None
        self.update_worker = None

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QHBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        self.game_tabs = QTabWidget()
        self.add_game_tab("Bagli Degil")

        self.pages = QStackedWidget()
        self.dashboard_page = self.create_dashboard_tab()
        self.pages.addWidget(self.dashboard_page)   # index 0
        self.pages.addWidget(self.game_tabs)        # index 1
        self.library_page = self.create_library_tab()
        self.pages.addWidget(self.library_page)     # index 2

        sidebar = self._build_sidebar()
        self.main_layout.addWidget(sidebar)
        self.main_layout.addWidget(self.pages, 1)

        self.init_log_dock()
        self.apply_theme()

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Hazir | Bir oyuna baglanarak basla.")

        # Arka plan dongusu: freeze uygula + tablo yenile
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(REFRESH_MS)

        # Baslangicta sessiz guncelleme kontrolu (kullanici acmissa ve
        # manifest URL girilmisse). Ag hatasi olursa sadece logla, rahatsiz etme.
        if self.app_config.get("auto_check_updates") and self.app_config.get("update_manifest_url"):
            QTimer.singleShot(1500, lambda: self._check_for_updates(silent=True))

    # ------------------------------------------------------------------
    def _log_safe(self, message: str):
        self.log(message)

    def init_log_dock(self):
        log_dock = QDockWidget("Sistem Loglari", self)
        log_dock.setAllowedAreas(Qt.BottomDockWidgetArea)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(120)
        log_dock.setWidget(self.log_text)
        self.addDockWidget(Qt.BottomDockWidgetArea, log_dock)

        # Loglari ayrica bir dosyaya da yaz - uygulama kapandiktan sonra
        # da hata ayiklamak/gecmisi incelemek icin.
        logs_dir = os.path.join(get_app_data_dir(), "logs")
        os.makedirs(logs_dir, exist_ok=True)
        session_name = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.log_file_path = os.path.join(logs_dir, f"session_{session_name}.log")

    def log(self, message):
        line = f"[SISTEM]: {message}"
        if hasattr(self, "log_text"):
            self.log_text.append(line)
        if hasattr(self, "log_file_path"):
            try:
                timestamp = datetime.now().strftime("%H:%M:%S")
                with open(self.log_file_path, "a", encoding="utf-8") as f:
                    f.write(f"[{timestamp}] {message}\n")
            except Exception:
                pass  # log dosyasina yazilamamasi uygulamayi durdurmamali

    # ------------------------------------------------------------------
    # SEKME ISKELETI
    # ------------------------------------------------------------------
    def add_game_tab(self, title):
        tab_widget = QWidget()
        layout = QVBoxLayout(tab_widget)

        sub_tabs = QTabWidget()
        sub_tabs.addTab(self.create_wizard_tab(), "\u2728 Trainer Wizard")
        sub_tabs.addTab(self.create_scanner_tab(), "Scanner & Auto AOB")
        sub_tabs.addTab(self.create_freeze_tab(), "Freeze Manager")
        sub_tabs.addTab(self.create_patch_tab(), "Disasm & Patch (Undo)")
        sub_tabs.addTab(self.create_script_tab(), "Script Engine")
        sub_tabs.addTab(self.create_update_tab(), "Guncelleme")

        layout.addWidget(sub_tabs)
        self.game_tabs.addTab(tab_widget, title)
        self.game_tab_widget = tab_widget
        self.sub_tabs = sub_tabs

    def _rename_game_tab(self, title: str):
        idx = self.game_tabs.indexOf(self.game_tab_widget)
        if idx >= 0:
            self.game_tabs.setTabText(idx, title)

    # ------------------------------------------------------------------
    # SOL MENU (SIDEBAR)
    # ------------------------------------------------------------------
    def _build_sidebar(self) -> QWidget:
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(190)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        brand = QWidget()
        brand.setObjectName("Brand")
        brand.setFixedHeight(56)
        brand_layout = QHBoxLayout(brand)
        brand_layout.setContentsMargins(0, 0, 0, 0)
        brand_layout.setSpacing(8)
        brand_layout.addStretch(1)
        brand_icon = QLabel()
        bolt_pix = get_pixmap("bolt", color="#7c5cff", size=20)
        if bolt_pix is not None:
            brand_icon.setPixmap(bolt_pix)
        else:
            brand_icon.setText("\u26A1")  # QtSvg yoksa emoji'ye sessizce geri don
        brand_layout.addWidget(brand_icon)
        brand_text = QLabel("LocalTrainer")
        brand_text.setStyleSheet("font-size: 15px; font-weight: bold; color: #ffffff;")
        brand_layout.addWidget(brand_text)
        brand_layout.addStretch(1)
        layout.addWidget(brand)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)

        nav_items = [
            ("home", "Ana Sayfa", "dashboard"),
            ("gamepad", "Trainer", "trainer"),
            ("grid", "Oyun Kutuphanesi", "library"),
            ("settings", "Ayarlar", "settings"),
        ]
        self.nav_buttons = []
        self._nav_key_to_button = {}
        for icon_name, label, key in nav_items:
            btn = QPushButton(f"  {label}")
            btn.setObjectName("NavButton")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            icon = get_icon(icon_name, color="#a7a8b3", size=18)
            if not icon.isNull():
                btn.setIcon(icon)
                btn.setIconSize(QSize(18, 18))
            btn.clicked.connect(lambda _, k=key: self._nav_clicked(k))
            layout.addWidget(btn)
            self.nav_group.addButton(btn)
            self.nav_buttons.append(btn)
            self._nav_key_to_button[key] = btn

        self.nav_buttons[0].setChecked(True)
        layout.addStretch(1)

        version_lbl = QLabel(f"v{updater.CURRENT_VERSION}")
        version_lbl.setObjectName("VersionLabel")
        version_lbl.setAlignment(Qt.AlignCenter)
        layout.addWidget(version_lbl)

        return sidebar

    def _nav_clicked(self, key: str):
        if key == "dashboard":
            self.pages.setCurrentIndex(0)
        elif key == "trainer":
            self.pages.setCurrentIndex(1)
        elif key == "library":
            self.pages.setCurrentIndex(2)
        elif key == "settings":
            # "Ayarlar" -> Trainer sayfasina gec ve Guncelleme sekmesini ac
            self.pages.setCurrentWidget(self.game_tabs)
            if hasattr(self, "sub_tabs"):
                self.sub_tabs.setCurrentIndex(self.sub_tabs.count() - 1)
        btn = self._nav_key_to_button.get(key)
        if btn is not None:
            btn.setChecked(True)

    # ------------------------------------------------------------------
    # DASHBOARD (ANA SAYFA)
    # ------------------------------------------------------------------
    def create_dashboard_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(16)

        title = QLabel("Ana Sayfa")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        subtitle = QLabel("Bir oyuna baglanarak veya kayitli bir profil yukleyerek basla.")
        subtitle.setObjectName("PageSubtitle")
        layout.addWidget(subtitle)

        # ---- Durum karti ----
        status_card = QFrame()
        status_card.setObjectName("Card")
        status_layout = QVBoxLayout(status_card)
        status_row = QHBoxLayout()
        self.dash_status_icon = QLabel()
        status_row.addWidget(self.dash_status_icon)
        self.dash_status_label = QLabel("Bagli degil")
        self.dash_status_label.setObjectName("DashStatus")
        status_row.addWidget(self.dash_status_label)
        status_row.addStretch(1)
        status_layout.addLayout(status_row)

        btn_row = QHBoxLayout()
        btn_go_wizard = QPushButton("  Trainer Wizard'i Ac")
        sparkle_icon = get_icon("sparkle", color="#ffffff", size=16)
        if not sparkle_icon.isNull():
            btn_go_wizard.setIcon(sparkle_icon)
            btn_go_wizard.setIconSize(QSize(16, 16))
        btn_go_wizard.clicked.connect(lambda: self._nav_clicked("trainer"))
        btn_row.addWidget(btn_go_wizard)
        btn_refresh_dash = QPushButton("  Yenile")
        refresh_icon = get_icon("refresh", color="#ffffff", size=16)
        if not refresh_icon.isNull():
            btn_refresh_dash.setIcon(refresh_icon)
            btn_refresh_dash.setIconSize(QSize(16, 16))
        btn_refresh_dash.clicked.connect(self._refresh_dashboard)
        btn_row.addWidget(btn_refresh_dash)
        btn_row.addStretch(1)
        status_layout.addLayout(btn_row)
        layout.addWidget(status_card)

        # ---- Kayitli profiller karti ----
        profiles_card = QFrame()
        profiles_card.setObjectName("Card")
        profiles_layout = QVBoxLayout(profiles_card)
        profiles_header_row = QHBoxLayout()
        folder_icon_lbl = QLabel()
        folder_pix = get_pixmap("folder", color="#c8c9d6", size=16)
        if folder_pix is not None:
            folder_icon_lbl.setPixmap(folder_pix)
        profiles_header_row.addWidget(folder_icon_lbl)
        profiles_header = QLabel("Kayitli Profiller")
        profiles_header.setObjectName("CardHeader")
        profiles_header_row.addWidget(profiles_header)
        profiles_header_row.addStretch(1)
        profiles_layout.addLayout(profiles_header_row)

        self.dash_profile_list = QListWidget()
        self.dash_profile_list.setMaximumHeight(220)
        profiles_layout.addWidget(self.dash_profile_list)
        layout.addWidget(profiles_card)

        layout.addStretch(1)
        self._refresh_dashboard()
        return widget

    def _refresh_dashboard(self):
        if hasattr(self, "engine") and self.engine.attached:
            base_str = f"0x{self.engine.base_address:X}" if self.engine.base_address else "bulunamadi"
            dot_color = "#4CAF50"
            status_text = f"Bagli \u2192 {self.engine.process_name}  (base={base_str})"
        else:
            dot_color = "#e53935"
            status_text = "Bagli degil"

        if hasattr(self, "dash_status_label"):
            self.dash_status_label.setText(status_text)
        if hasattr(self, "dash_status_icon"):
            dot_pix = get_pixmap("circle", color=dot_color, size=12)
            if dot_pix is not None:
                self.dash_status_icon.setPixmap(dot_pix)
            else:
                self.dash_status_icon.setText("\U0001F534" if dot_color == "#e53935" else "\U0001F7E2")

        if hasattr(self, "dash_profile_list"):
            self.dash_profile_list.clear()
            try:
                names = sorted(list_profiles())
            except Exception:
                names = []
            if not names:
                self.dash_profile_list.addItem("(kayitli profil yok)")
            else:
                self.dash_profile_list.addItems(names)

    # ------------------------------------------------------------------
    # OYUN KUTUPHANESI (Steam/Epic/GOG/Xbox otomatik algilama)
    # ------------------------------------------------------------------
    def create_library_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(16)

        title = QLabel("Oyun Kutuphanesi")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        subtitle = QLabel(
            "Steam, Epic Games, GOG ve Xbox (Microsoft Store) uzerinden kurulu "
            "oyunlari otomatik bulur. Sadece Windows'ta calisir."
        )
        subtitle.setObjectName("PageSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        card = QFrame()
        card.setObjectName("Card")
        card_layout = QVBoxLayout(card)

        toolbar = QHBoxLayout()
        self.btn_scan_library = QPushButton("  Kutuphaneyi Tara")
        refresh_icon = get_icon("refresh", color="#ffffff", size=16)
        if not refresh_icon.isNull():
            self.btn_scan_library.setIcon(refresh_icon)
            self.btn_scan_library.setIconSize(QSize(16, 16))
        self.btn_scan_library.clicked.connect(self._scan_library)
        toolbar.addWidget(self.btn_scan_library)

        self.library_status_label = QLabel("Henuz taranmadi.")
        self.library_status_label.setObjectName("PageSubtitle")
        toolbar.addWidget(self.library_status_label)
        toolbar.addStretch(1)
        card_layout.addLayout(toolbar)

        self.library_scroll = QScrollArea()
        self.library_scroll.setObjectName("LibraryScroll")
        self.library_scroll.setWidgetResizable(True)
        self.library_grid_container = QWidget()
        self.library_grid = QGridLayout(self.library_grid_container)
        self.library_grid.setSpacing(14)
        self.library_grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.library_scroll.setWidget(self.library_grid_container)
        card_layout.addWidget(self.library_scroll, 1)

        hint = QLabel(
            "Cift tikla: Trainer Wizard'a gonderir ve process adini doldurur. "
            "Attach islemi icin oyunun ACIK/CALISIYOR olmasi gerekir. Kapak "
            "gorselleri sadece Steam oyunlari icin otomatik indirilir."
        )
        hint.setObjectName("PageSubtitle")
        hint.setWordWrap(True)
        card_layout.addWidget(hint)

        layout.addWidget(card, 1)
        self._library_generation = 0
        self._library_cards = []
        return widget

    def _scan_library(self):
        self.btn_scan_library.setEnabled(False)
        self.library_status_label.setText("Taraniyor... (Steam / Epic / GOG / Xbox)")
        worker = ScanWorker(scan_all_libraries)
        worker.finished_ok.connect(self._on_library_scan_done)
        worker.finished_error.connect(self._on_library_scan_error)
        self._library_worker = worker  # tarama bitene kadar referansi tut (gc onlemi)
        worker.start()

    def _on_library_scan_done(self, games):
        self.btn_scan_library.setEnabled(True)
        self._populate_library_grid(games)
        self.log(f"Oyun kutuphanesi tarandi: {len(games)} oyun bulundu.")

    def _on_library_scan_error(self, msg: str):
        self.btn_scan_library.setEnabled(True)
        self.library_status_label.setText("Tarama hatasi.")
        self.log(f"Kutuphane tarama hatasi: {msg}")

    def _populate_library_grid(self, games):
        self._library_games = games

        # Onceki kartlari temizle (yeniden tarama sonrasi).
        while self.library_grid.count():
            item = self.library_grid.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._library_cards = []

        columns = 6
        for i, g in enumerate(games):
            card = GameCard(i, g)
            card.activated.connect(self._on_library_card_activated)
            self.library_grid.addWidget(card, i // columns, i % columns)
            self._library_cards.append(card)

        if games:
            self.library_status_label.setText(f"{len(games)} oyun bulundu.")
        else:
            self.library_status_label.setText(
                "Oyun bulunamadi. (Bu ozellik sadece Windows'ta ve Steam/Epic/GOG/Xbox "
                "kuruluysa calisir.)"
            )

        # Kapaklari (sadece Steam, sadece henuz onbellekte olmayanlar icin)
        # arka planda indir. _library_generation, kullanici hizlica tekrar
        # tararsa eski bir tarama turunun sonuclarinin yeni (farkli indexli)
        # kartlara yanlislikla yazilmasini onler.
        self._library_generation += 1
        gen = self._library_generation
        self._cover_worker = CoverFetchWorker(games)
        self._cover_worker.cover_ready.connect(
            lambda idx, path, gen=gen: self._on_cover_ready(gen, idx, path)
        )
        self._cover_worker.start()

    def _on_cover_ready(self, gen: int, index: int, path: str):
        if gen != self._library_generation:
            return  # eski bir tarama turundan kalma sonuc - artik gecersiz
        if 0 <= index < len(self._library_cards):
            self._library_cards[index].set_cover(path)

    def _on_library_card_activated(self, index: int):
        games = getattr(self, "_library_games", [])
        if index < 0 or index >= len(games):
            return
        game = games[index]
        proc_name = game.process_name
        if not proc_name:
            QMessageBox.information(
                self, "Bilgi",
                f"'{game.name}' icin calistirilabilir dosya otomatik bulunamadi.\n"
                "Trainer Wizard'da '.exe Sec' ile elle secebilirsin."
            )
            return
        self.wiz_process_combo.setEditText(proc_name)
        self._nav_clicked("trainer")
        if hasattr(self, "sub_tabs"):
            self.sub_tabs.setCurrentIndex(0)
        self.log(
            f"Kutuphaneden secildi: {game.name} ({game.source}) -> {proc_name}. "
            "Oyun acik degilse once ac, sonra Attach'e bas."
        )

    # ------------------------------------------------------------------
    # 1) TRAINER WIZARD
    # ------------------------------------------------------------------
    def create_wizard_tab(self):
        widget = QWidget()
        layout = QHBoxLayout(widget)

        step_list = QListWidget()
        step_list.addItems([
            "1. Game Attach", "2. Scan Values",
            "3. Freeze Pointers", "4. Build Trainer.exe",
        ])
        step_list.setCurrentRow(0)
        step_list.setMaximumWidth(200)

        stack = QStackedWidget()

        # --- Sayfa 1: Attach ---
        page1 = QWidget()
        p1 = QVBoxLayout(page1)
        p1.addWidget(QLabel("Hedef Oyunu Secin ve Attach Islemini Gerceklestirin."))

        row = QHBoxLayout()
        self.wiz_process_combo = QComboBox()
        self.wiz_process_combo.setEditable(True)
        row.addWidget(self.wiz_process_combo)
        btn_refresh = QPushButton("Listeyi Yenile")
        btn_refresh.clicked.connect(self._refresh_process_list)
        row.addWidget(btn_refresh)
        btn_exe = QPushButton(".exe Sec")
        btn_exe.clicked.connect(self._pick_exe)
        row.addWidget(btn_exe)
        p1.addLayout(row)

        self.show_all_processes_check = QCheckBox(
            "Tum process'leri goster (servisler/arka plan dahil - kalabalik olur)"
        )
        self.show_all_processes_check.stateChanged.connect(lambda _: self._refresh_process_list())
        p1.addWidget(self.show_all_processes_check)

        btn_attach = QPushButton("Oyuna Baglan (Attach)")
        btn_attach.clicked.connect(self._attach)
        p1.addWidget(btn_attach)

        btn_detach = QPushButton("Baglantiyi Kes (Detach)")
        btn_detach.setStyleSheet("background-color: #555555;")
        btn_detach.clicked.connect(self._detach)
        p1.addWidget(btn_detach)

        self.wiz_attach_status = QLabel("Durum: bagli degil")
        p1.addWidget(self.wiz_attach_status)

        profile_row = QHBoxLayout()
        profile_row.addWidget(QLabel("Kayitli profiller:"))
        self.profile_combo = QComboBox()
        profile_row.addWidget(self.profile_combo)
        btn_load_profile = QPushButton("Secili Profili Yukle")
        btn_load_profile.clicked.connect(self._manual_load_profile)
        profile_row.addWidget(btn_load_profile)
        btn_export_profile = QPushButton("Disa Aktar")
        btn_export_profile.clicked.connect(self._export_profile)
        profile_row.addWidget(btn_export_profile)
        btn_import_profile = QPushButton("Ice Aktar")
        btn_import_profile.clicked.connect(self._import_profile)
        profile_row.addWidget(btn_import_profile)
        p1.addLayout(profile_row)
        self._refresh_profile_combo()

        p1.addStretch()
        stack.addWidget(page1)

        # --- Sayfa 2: Scan Values (bilgi + Scanner sekmesine yonlendirme) ---
        page2 = QWidget()
        p2 = QVBoxLayout(page2)
        p2.addWidget(QLabel(
            "Deger tarama islemini 'Scanner & Auto AOB' sekmesinden yap:\n"
            "1) Bilinen bir degeri (ornek: can miktari) gir, Ilk Tarama'ya bas.\n"
            "2) Oyunda o degeri degistir.\n"
            "3) Yeni degeri gir, Sonraki Tarama'ya bas. Tek adrese inene kadar tekrarla."
        ))
        p2.addStretch()
        stack.addWidget(page2)

        # --- Sayfa 3: Freeze Pointers (bilgi + Freeze Manager'a yonlendirme) ---
        page3 = QWidget()
        p3 = QVBoxLayout(page3)
        p3.addWidget(QLabel(
            "Bulunan adresi 'Freeze Manager' sekmesine ekleyip dondur.\n"
            "Kalici (surumler arasi degismeyen) adres icin pointer/AOB zinciri kullan."
        ))
        p3.addStretch()
        stack.addWidget(page3)

        # --- Sayfa 4: Build Trainer.exe ---
        page4 = QWidget()
        p4 = QVBoxLayout(page4)
        p4.addWidget(QLabel(
            "Su anki ayarlari (Freeze Manager listesi) bagimsiz bir profil olarak\n"
            "kaydet. Gercek .exe derlemesi PyInstaller gerektirir ve KAYNAK KODDAN\n"
            "calistirildiginda (derlenmis .exe icinden degil) yapilabilir:\n\n"
            "    pyinstaller --onefile --noconsole --name LocalTrainerStudio main.py\n\n"
            "Asagidaki buton mevcut profili kaydeder (Freeze Manager sekmesindeki\n"
            "'Profili Kaydet' ile ayni islevi gorur)."
        ))
        btn_save_profile_w = QPushButton("Profili Kaydet")
        btn_save_profile_w.clicked.connect(self._save_current_profile)
        p4.addWidget(btn_save_profile_w)
        p4.addStretch()
        stack.addWidget(page4)

        step_list.currentRowChanged.connect(stack.setCurrentIndex)

        layout.addWidget(step_list)
        layout.addWidget(stack)
        return widget

    def _refresh_process_list(self):
        show_all = self.show_all_processes_check.isChecked()
        try:
            procs = list_processes() if show_all else list_processes_with_windows()
        except Exception as e:
            QMessageBox.critical(self, "Hata", f"Process listesi alinamadi:\n{e}")
            return
        names = sorted({name for _, name in procs})
        self.wiz_process_combo.clear()
        self.wiz_process_combo.addItems(names)
        kind = "tum process" if show_all else "gorunur pencereli uygulama"
        self.log(f"{len(names)} {kind} bulundu.")

    def _pick_exe(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Oyunun .exe dosyasini sec", "", "Uygulama (*.exe);;Tum dosyalar (*.*)"
        )
        if path:
            import os
            exe_name = os.path.basename(path)
            self.wiz_process_combo.setEditText(exe_name)
            self.log(f"Secildi: {exe_name} (once oyunu ac, sonra Attach'e bas)")

    def _attach(self):
        process_name = self.wiz_process_combo.currentText().strip()
        if not process_name:
            QMessageBox.warning(self, "Uyari", "Once bir process sec veya .exe sec.")
            return
        try:
            self.engine.attach(process_name)
        except Exception as e:
            QMessageBox.critical(
                self, "Baglanamadi",
                f"'{process_name}' processine baglanilamadi.\n"
                f"Oyun acik mi? Uygulamayi yonetici olarak calistirdin mi?\n\nDetay: {e}",
            )
            self.wiz_attach_status.setText("Durum: baglanti hatasi")
            return

        # Farkli/yeni bir process'e baglanildiginda ONCEKI oyunun watch
        # list/hotkey/patch bilgileri temizlenir. Aksi halde eski adresler
        # yeni process'in bellegine (yanlislikla, tehlikeli sekilde) yazilmaya
        # devam edebilirdi.
        self.hotkeys.unregister_all()
        self.watched.clear()
        self.byte_patches.clear()
        self.patch_list.clear()
        self.script_engine = ScriptEngine(self.engine, on_log=self._log_safe)
        self.current_game_label = ""

        if self.engine.base_address is not None:
            base_str = f"0x{self.engine.base_address:X}"
        else:
            base_str = f"BULUNAMADI ({self.engine.base_address_error})"
        self.wiz_attach_status.setText(f"Durum: BAGLI -> {process_name} (base={base_str})")
        self._rename_game_tab(process_name)
        self.status_bar.showMessage(f"Bagli: {process_name}")
        self.log(f"Baglanildi: {process_name}")
        if self.engine.base_address is None:
            self.log(
                "UYARI: module base adresi bulunamadi - pointer zinciri "
                "(kalici profil) calismayacak, ama manuel/AOB adres ekleme calisir."
            )
        self._refresh_freeze_table()
        self._try_autoload_profile(process_name)
        self._refresh_dashboard()
        self._nav_clicked("trainer")

    def _detach(self):
        self.hotkeys.unregister_all()
        self.engine.detach()
        self.watched.clear()
        self.byte_patches.clear()
        self.patch_list.clear()
        self._refresh_freeze_table()
        self.wiz_attach_status.setText("Durum: bagli degil")
        self._rename_game_tab("Bagli Degil")
        self.status_bar.showMessage("Baglanti kesildi.")
        self.log("Baglanti kesildi.")
        self._refresh_dashboard()

    def _try_autoload_profile(self, process_name):
        if not profile_exists(process_name):
            self.log("Bu oyun icin kayitli profil yok, taramaya basla.")
            return
        self._load_profile_data(load_profile(process_name))

    def _load_profile_data(self, data: Optional[dict]):
        if not data:
            return
        self.current_game_label = data.get("game_label", self.engine.process_name or "")
        self.watched.clear()
        permanent_count = 0
        temp_count = 0
        for c in data.get("cheats", []):
            offsets = c.get("offsets", [])
            wa = WatchedAddress(
                name=c["name"], address=c.get("address", 0), value_type=c["value_type"],
                offsets=offsets, hotkey=c.get("hotkey"),
            )
            self.watched.append(wa)
            if wa.hotkey:
                self._bind_hotkey(wa)
            if offsets:
                permanent_count += 1
            else:
                temp_count += 1
        self._refresh_freeze_table()
        self.log(f"'{self.current_game_label}' profili yuklendi ({len(self.watched)} cheat).")
        if temp_count:
            self.log(
                f"  -> {temp_count} tanesi ham adres (pointer zinciri yok); "
                "bu oyun kapatilip yeniden acildiysa gecersiz olabilir."
            )
        if permanent_count:
            self.log(f"  -> {permanent_count} tanesi kalici pointer zinciri, her zaman gecerli.")

    def _refresh_profile_combo(self):
        from profile_manager import list_profiles
        self.profile_combo.clear()
        self.profile_combo.addItems(list_profiles())

    def _manual_load_profile(self):
        if not self._require_attached():
            return
        process_name = self.profile_combo.currentText().strip()
        if not process_name:
            QMessageBox.information(self, "Bilgi", "Yuklenecek bir profil sec.")
            return
        data = load_profile(process_name)
        if not data:
            QMessageBox.warning(self, "Uyari", f"'{process_name}' profili bulunamadi.")
            return
        self.hotkeys.unregister_all()
        self._load_profile_data(data)

    def _export_profile(self):
        """Secili profili baska bir bilgisayara tasimak/paylasmak icin
        ayri bir .json dosyasi olarak diska kaydeder."""
        process_name = self.profile_combo.currentText().strip()
        if not process_name:
            QMessageBox.information(self, "Bilgi", "Disa aktarilacak bir profil sec.")
            return
        src_path = os.path.join(PROFILES_DIR, f"{process_name}.json")
        if not os.path.exists(src_path):
            QMessageBox.warning(self, "Uyari", "Profil dosyasi bulunamadi.")
            return
        dest_path, _ = QFileDialog.getSaveFileName(
            self, "Profili disa aktar", f"{process_name}.json", "JSON (*.json)"
        )
        if not dest_path:
            return
        import shutil
        shutil.copyfile(src_path, dest_path)
        self.log(f"Profil disa aktarildi: {dest_path}")
        QMessageBox.information(self, "Basarili", f"Profil kaydedildi:\n{dest_path}")

    def _import_profile(self):
        """Baska bir bilgisayardan/kisiden alinan bir profil .json dosyasini
        kendi profiller klasorune ekler."""
        src_path, _ = QFileDialog.getOpenFileName(
            self, "Profil ice aktar", "", "JSON (*.json)"
        )
        if not src_path:
            return
        try:
            with open(src_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            QMessageBox.critical(self, "Hata", f"Dosya okunamadi:\n{e}")
            return
        process_name = data.get("process_name")
        if not process_name:
            QMessageBox.warning(self, "Uyari", "Bu dosya gecerli bir profil gibi gorunmuyor (process_name eksik).")
            return
        os.makedirs(PROFILES_DIR, exist_ok=True)
        dest_path = os.path.join(PROFILES_DIR, f"{process_name}.json")
        if os.path.exists(dest_path):
            reply = QMessageBox.question(
                self, "Uzerine yazilsin mi?",
                f"'{process_name}' icin zaten bir profil var. Uzerine yazilsin mi?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return
        import shutil
        shutil.copyfile(src_path, dest_path)
        self._refresh_profile_combo()
        self.log(f"Profil ice aktarildi: {process_name}")
        QMessageBox.information(self, "Basarili", f"'{process_name}' profili eklendi. Simdi listeden secip yukleyebilirsin.")

    def _require_attached(self) -> bool:
        if not self.engine.attached:
            QMessageBox.warning(self, "Uyari", "Once bir oyuna baglanmalisin.")
            return False
        return True

    def _run_scan_in_background(self, status_message: str, fn, on_success, *args, **kwargs):
        """
        Herhangi bir agir MemoryEngine cagrisini ScanWorker uzerinden arka
        planda calistirir; sonuc gelince on_success(result) cagrilir.
        Ayni anda birden fazla tarama calismasini engeller (MemoryEngine
        ic durumu - _last_results vb. - es zamanli erisime karsi guvenli
        degildir).
        """
        if getattr(self, "_scan_running", False):
            QMessageBox.information(
                self, "Bilgi", "Zaten devam eden bir tarama var, bitmesini bekle."
            )
            return
        self._scan_running = True
        self._set_scan_buttons_enabled(False)
        self.status_bar.showMessage(status_message)

        self.scan_worker = ScanWorker(fn, *args, **kwargs)

        def _on_ok(result):
            self._scan_running = False
            self._set_scan_buttons_enabled(True)
            on_success(result)

        def _on_error(error_msg):
            self._scan_running = False
            self._set_scan_buttons_enabled(True)
            self.status_bar.showMessage("Hazir.")
            QMessageBox.critical(self, "Hata", f"Tarama hatasi:\n{error_msg}")

        self.scan_worker.finished_ok.connect(_on_ok)
        self.scan_worker.finished_error.connect(_on_error)
        self.scan_worker.start()

    def _set_scan_buttons_enabled(self, enabled: bool):
        """Tarama sirasinda ayni islemi tekrar tetiklemeyi engellemek icin
        ilgili butonlari devre disi birakir/geri acar."""
        for attr_name in (
            "btn_first_scan", "btn_next_scan", "btn_unknown_first_scan",
            "btn_unknown_next_scan", "btn_aob_scan", "btn_pointer_scan",
        ):
            btn = getattr(self, attr_name, None)
            if btn is not None:
                btn.setEnabled(enabled)

    # ------------------------------------------------------------------
    # 2) SCANNER & AUTO AOB
    # ------------------------------------------------------------------
    def create_scanner_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        splitter = QSplitter(Qt.Vertical)

        # ---- Basit / Gelismis gecisi ----
        mode_row = QHBoxLayout()
        self.scan_status_label = QLabel("Oyunda gordugun degeri gir ve ara.")
        self.scan_status_label.setStyleSheet("color: #c8c9d6; font-weight: 600;")
        mode_row.addWidget(self.scan_status_label)
        mode_row.addStretch(1)
        self.btn_toggle_advanced = QPushButton("Gelismis \u25be")
        self.btn_toggle_advanced.setCheckable(True)
        self.btn_toggle_advanced.setToolTip(
            "Tip/mod secimi, Bilinmeyen Ilk Deger taramasi, AOB/Pattern\n"
            "taramasi ve adres sutunu gibi teknik alanlari acar/kapatir."
        )
        self.btn_toggle_advanced.toggled.connect(self._toggle_scanner_advanced)
        mode_row.addWidget(self.btn_toggle_advanced)
        layout.addLayout(mode_row)

        # ---- Manuel deger tarama ----
        scan_box = QGroupBox("Manuel Tarama")
        scan_v = QVBoxLayout(scan_box)

        row0 = QHBoxLayout()
        self.scan_type_label = QLabel("Tip:")
        row0.addWidget(self.scan_type_label)
        self.scan_type_combo = QComboBox()
        self.scan_type_combo.addItems(ALL_TYPES)
        row0.addWidget(self.scan_type_combo)
        row0.addWidget(QLabel("Deger:"))
        self.scan_value_edit = QLineEdit(placeholderText="Aranacak/Yeni Deger...")
        row0.addWidget(self.scan_value_edit)
        self.btn_first_scan = btn_first = QPushButton("First Scan")
        btn_first.clicked.connect(self._first_scan)
        row0.addWidget(btn_first)

        self.scan_mode_combo = QComboBox()
        self.scan_mode_combo.addItems(["exact", "changed", "unchanged", "increased", "decreased"])
        row0.addWidget(self.scan_mode_combo)
        self.btn_next_scan = btn_next = QPushButton("Next Scan")
        btn_next.clicked.connect(self._next_scan)
        row0.addWidget(btn_next)
        scan_v.addLayout(row0)

        # ---- Bilinmeyen Ilk Deger (Unknown Initial Value) - GELISMIS ----
        self.advanced_unknown_box = QWidget()
        unknown_row = QHBoxLayout(self.advanced_unknown_box)
        unknown_row.setContentsMargins(0, 0, 0, 0)
        self.btn_unknown_first_scan = btn_unknown_first = QPushButton("Bilinmeyen Ilk Deger: Tara")
        btn_unknown_first.setToolTip(
            "Aranan sayiyi bilmiyorsan kullan. Once bu butona bas (tum bellegin\n"
            "anlik goruntusunu alir), sonra oyunda degeri degistir, sonra asagidaki\n"
            "modla (changed/increased/decreased) filtrele. AGIR bir islemdir."
        )
        btn_unknown_first.clicked.connect(self._unknown_first_scan)
        unknown_row.addWidget(btn_unknown_first)
        self.unknown_mode_combo = QComboBox()
        self.unknown_mode_combo.addItems(["changed", "unchanged", "increased", "decreased"])
        unknown_row.addWidget(self.unknown_mode_combo)
        self.btn_unknown_next_scan = btn_unknown_next = QPushButton("Bilinmeyen: Filtrele")
        btn_unknown_next.clicked.connect(self._unknown_next_scan)
        unknown_row.addWidget(btn_unknown_next)
        scan_v.addWidget(self.advanced_unknown_box)

        self.advanced_hint_label = QLabel(
            "Ipucu: 'byte' tipi ve 14 gibi cok yaygin bir sayi binlerce tesadufi\n"
            "eslesme bulur - bunlarin cogu gercek stat'la ilgisizdir ve Next Scan'de\n"
            "elenir. Can/mana/altin gibi degerler icin genelde 'int32' veya 'float'\n"
            "kullan ve mumkunse daha az rastlanan (ozgun) bir sayiyla basla."
        )
        self.advanced_hint_label.setStyleSheet("color: #90caf9;")
        scan_v.addWidget(self.advanced_hint_label)

        self.scan_result_table = QTableWidget(0, 2)
        self.scan_result_table.setHorizontalHeaderLabels(["Adres", "Deger"])
        self.scan_result_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.scan_result_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.scan_result_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.scan_result_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.scan_result_table.itemDoubleClicked.connect(self._add_scan_result_to_watchlist)
        scan_v.addWidget(self.scan_result_table)
        result_btn_row = QHBoxLayout()
        self.scan_result_label = QLabel("Sonuc: 0")
        result_btn_row.addWidget(self.scan_result_label)
        result_btn_row.addStretch()
        btn_bulk_add = QPushButton("Secilenleri Toplu Ekle (Ctrl/Shift ile coklu sec)")
        btn_bulk_add.setToolTip(
            "Tabloda birden fazla satiri Ctrl+tik veya Shift+tik ile secip\n"
            "buna bas: hepsi tek seferde, tek isim sorusuyla Freeze Manager'a\n"
            "eklenir (her biri icin ayri ayri isim sormaz)."
        )
        btn_bulk_add.clicked.connect(self._add_selected_scan_results_to_watchlist)
        result_btn_row.addWidget(btn_bulk_add)
        scan_v.addLayout(result_btn_row)

        # ---- AOB / Pattern tarama - GELISMIS ----
        self.aob_box = aob_box = QGroupBox("Auto Signature (AOB) Builder")
        aob_layout = QVBoxLayout(aob_box)
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Pattern:"))
        self.aob_pattern_edit = QLineEdit(placeholderText="Ornek: A1 ?? ?? ?? ?? 8B 45 FC")
        row1.addWidget(self.aob_pattern_edit)
        self.btn_aob_scan = btn_aob_scan = QPushButton("Tara")
        btn_aob_scan.clicked.connect(self._aob_scan)
        row1.addWidget(btn_aob_scan)
        aob_layout.addLayout(row1)

        self.aob_result_list = QListWidget()
        self.aob_result_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.aob_result_list.itemDoubleClicked.connect(self._add_aob_result_to_watchlist)
        aob_layout.addWidget(self.aob_result_list)

        self.aob_parallel_checkbox = QCheckBox("Cok cekirdekli tara (deneysel)")
        self.aob_parallel_checkbox.setToolTip(
            "Bellek taramasini birden fazla PROCESS'e boler (multiprocessing) - "
            "threading DEGIL, cunku Python'daki GIL bu CPU-bound isi thread'lerle "
            "paralellestirmeyi anlamsiz kilar. Buyuk (GB'larca) bellekte cok "
            "cekirdekli CPU'larda hizlanma saglar; kucuk taramalarda process "
            "baslatma maliyeti yuzunden fayda saglamayabilir. Basarisiz olursa "
            "sessizce tek-cekirdek taramaya duser."
        )
        aob_layout.addWidget(self.aob_parallel_checkbox)

        aob_layout.addWidget(QLabel(
            "Not: '??' bilinmeyen/degisken byte anlamina gelir. Cift tiklayarak\n"
            "tek bir adresi, ya da Ctrl/Shift ile birden fazla secip asagidaki\n"
            "butonla hepsini tek seferde Freeze Manager listesine ekleyebilirsin."
        ))
        btn_aob_bulk_add = QPushButton("Secilenleri Toplu Ekle")
        btn_aob_bulk_add.clicked.connect(self._add_selected_aob_results_to_watchlist)
        aob_layout.addWidget(btn_aob_bulk_add)

        splitter.addWidget(scan_box)
        splitter.addWidget(aob_box)
        layout.addWidget(splitter)
        self.btn_toggle_advanced.setChecked(False)
        self._toggle_scanner_advanced(False)
        return widget

    def _toggle_scanner_advanced(self, checked: bool):
        """Scan ekranini sadelestirir: Tip/mod secimi, Bilinmeyen Ilk Deger
        taramasi, AOB/Pattern taramasi ve sonuc tablosundaki ham Adres
        sutunu gibi teknik alanlar varsayilan olarak GIZLI - sadece
        'Gelismis' acilinca gorunur. Basit modda kullanici sadece bir
        deger girip arar, tipki WeMod/basit trainer arayuzlerindeki gibi."""
        self.scan_type_label.setVisible(checked)
        self.scan_type_combo.setVisible(checked)
        self.scan_mode_combo.setVisible(checked)
        self.advanced_unknown_box.setVisible(checked)
        self.advanced_hint_label.setVisible(checked)
        self.aob_box.setVisible(checked)
        self.scan_result_table.setColumnHidden(0, not checked)
        if checked:
            self.btn_toggle_advanced.setText("Gelismis \u25b4")
            self.scan_status_label.setText("Gelismis mod: tip, mod, AOB ve adresler gorunuyor.")
        else:
            self.btn_toggle_advanced.setText("Gelismis \u25be")
            self.scan_status_label.setText("Oyunda gordugun degeri gir ve ara.")

    def _unknown_first_scan(self):
        if not self._require_attached():
            return
        vtype = self.scan_type_combo.currentText()
        reply = QMessageBox.question(
            self, "Emin misin?",
            "Bu islem TUM bellegin bir anlik goruntusunu alir ve biraz zaman/RAM\n"
            "harcayabilir (buyuk oyunlarda onlarca saniye surebilir). Arayuz bu\n"
            "sirada yanit vermeye devam edecek. Devam edilsin mi?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        def on_success(count):
            self.status_bar.showMessage(f"Snapshot alindi: {count} adres izleniyor.")
            self.log(
                f"Bilinmeyen ilk deger snapshot'i alindi ({count} adres, tip={vtype}). "
                "Simdi oyunda degeri degistir ve 'Bilinmeyen: Filtrele'ye bas."
            )

        self._run_scan_in_background(
            "Bilinmeyen ilk deger taraniyor (snapshot aliniyor)...",
            self.engine.first_scan_unknown, on_success, vtype,
        )

    def _unknown_next_scan(self):
        if not self._require_attached():
            return
        mode = self.unknown_mode_combo.currentText()
        self._run_scan_in_background(
            "Filtreleniyor...", self.engine.next_scan_unknown,
            self._populate_scan_results, mode=mode,
        )

    def _first_scan(self):
        if not self._require_attached():
            return
        vtype = self.scan_type_combo.currentText()
        raw = self.scan_value_edit.text()
        try:
            value = float(raw) if vtype in ("float", "double") else int(raw)
        except ValueError:
            QMessageBox.warning(self, "Uyari", "Gecerli bir deger gir.")
            return
        self.scan_status_label.setText(f"'{raw}' araniyor...")
        self._run_scan_in_background(
            "Taraniyor...", self.engine.first_scan,
            self._populate_scan_results, value, vtype,
        )

    def _next_scan(self):
        if not self._require_attached():
            return
        vtype = self.scan_type_combo.currentText()
        mode = self.scan_mode_combo.currentText()
        value = None
        if mode == "exact":
            raw = self.scan_value_edit.text()
            try:
                value = float(raw) if vtype in ("float", "double") else int(raw)
            except ValueError:
                QMessageBox.warning(self, "Uyari", "Gecerli bir deger gir.")
                return
        self.scan_status_label.setText("Yeniden araniyor...")
        self._run_scan_in_background(
            "Taraniyor...", self.engine.next_scan,
            self._populate_scan_results, vtype, mode=mode, value=value,
        )

    def _populate_scan_results(self, results):
        self.scan_result_table.setRowCount(0)
        for r in results[:500]:
            row = self.scan_result_table.rowCount()
            self.scan_result_table.insertRow(row)
            self.scan_result_table.setItem(row, 0, QTableWidgetItem(hex(r.address)))
            self.scan_result_table.setItem(row, 1, QTableWidgetItem(str(r.value)))
        extra = " (ilk 500 gosteriliyor)" if len(results) > 500 else ""
        if getattr(self.engine, "last_scan_truncated", False):
            extra += " - COK FAZLA SONUC, liste kesildi. Daha ozgun bir deger/tip dene."
        self.scan_result_label.setText(f"Sonuc: {len(results)}{extra}")
        self.status_bar.showMessage("Tarama tamamlandi.")
        if not self.btn_toggle_advanced.isChecked():
            if len(results) == 0:
                self.scan_status_label.setText("Sonuc yok - oyunda degeri degistirip tekrar dene.")
            elif len(results) == 1:
                self.scan_status_label.setText("1 sonuc bulundu - listeye cift tikla ve ekle.")
            else:
                self.scan_status_label.setText(
                    f"{len(results)} sonuc bulundu - oyunda degeri degistir, "
                    "yeni degeri gir ve 'Next Scan'e bas."
                )
        if len(results) == 0:
            self.log(
                "Next Scan sonucu 0 -> muhtemelen onceki turdaki eslesmeler "
                "tesadufiydi (yanlis tip/cok yaygin deger). First Scan'e "
                "farkli bir tip (int32/float) ve daha ozgun bir sayiyla yeniden basla."
            )

    def _add_scan_result_to_watchlist(self, item):
        row = item.row()
        addr_str = self.scan_result_table.item(row, 0).text()
        address = int(addr_str, 16)
        name, ok = QInputDialog.getText(self, "Isim ver", "Bu cheat icin bir isim:")
        if not ok or not name:
            return
        wa = WatchedAddress(name=name, address=address, value_type=self.scan_type_combo.currentText())
        self.watched.append(wa)
        self._refresh_freeze_table()
        self.log(f"'{name}' Freeze Manager'a eklendi.")

    def _add_selected_scan_results_to_watchlist(self):
        """Tabloda secili birden fazla satiri TEK bir isim sorusuyla topluca
        Freeze Manager'a ekler (her satir icin ayri ayri dialog acmaz).
        Isimler 'Taban Isim 1', 'Taban Isim 2' ... seklinde numaralanir."""
        rows = sorted({idx.row() for idx in self.scan_result_table.selectedIndexes()})
        if not rows:
            QMessageBox.information(self, "Bilgi", "Once tabloda bir veya daha fazla satir sec (Ctrl/Shift ile).")
            return
        base_name, ok = QInputDialog.getText(
            self, "Toplu Isim", f"{len(rows)} adres icin taban isim (ornek: 'Can'):"
        )
        if not ok or not base_name:
            return
        vtype = self.scan_type_combo.currentText()
        added = 0
        for i, row in enumerate(rows):
            item = self.scan_result_table.item(row, 0)
            if item is None:
                continue
            address = int(item.text(), 16)
            name = base_name if len(rows) == 1 else f"{base_name} {i + 1}"
            self.watched.append(WatchedAddress(name=name, address=address, value_type=vtype))
            added += 1
        self._refresh_freeze_table()
        self.log(f"{added} adres '{base_name}' adiyla topluca Freeze Manager'a eklendi.")

    def _add_selected_aob_results_to_watchlist(self):
        """AOB sonuc listesindeki secili birden fazla adresi TEK bir isim ve
        tip sorusuyla topluca Freeze Manager'a ekler."""
        items = self.aob_result_list.selectedItems()
        if not items:
            QMessageBox.information(self, "Bilgi", "Once listede bir veya daha fazla sonuc sec (Ctrl/Shift ile).")
            return
        base_name, ok = QInputDialog.getText(
            self, "Toplu Isim", f"{len(items)} adres icin taban isim:"
        )
        if not ok or not base_name:
            return
        vtype, ok2 = QInputDialog.getItem(
            self, "Deger tipi", "Bu adresler icin deger tipi:",
            ALL_TYPES, editable=False,
        )
        if not ok2:
            vtype = "int32"
        added = 0
        for i, item in enumerate(items):
            address = int(item.text(), 16)
            name = base_name if len(items) == 1 else f"{base_name} {i + 1}"
            self.watched.append(WatchedAddress(name=name, address=address, value_type=vtype))
            added += 1
        self._refresh_freeze_table()
        self.log(f"{added} adres (AOB) '{base_name}' adiyla topluca Freeze Manager'a eklendi.")

    def _aob_scan(self):
        if not self._require_attached():
            return
        pattern = self.aob_pattern_edit.text().strip()
        if not pattern:
            QMessageBox.warning(self, "Uyari", "Bir pattern gir (ornek: A1 ?? ?? ?? ??).")
            return

        def on_success(addresses):
            self.aob_result_list.clear()
            for addr in addresses:
                self.aob_result_list.addItem(hex(addr))
            self.status_bar.showMessage(f"AOB tarama tamamlandi: {len(addresses)} sonuc.")

        if self.aob_parallel_checkbox.isChecked():
            self._run_scan_in_background(
                "AOB taraniyor (cok cekirdekli)...",
                self.engine.pattern_scan_parallel, on_success, pattern, max_results=200,
            )
        else:
            self._run_scan_in_background(
                "AOB taraniyor (buyuk bellekte biraz surebilir)...",
                self.engine.pattern_scan, on_success, pattern, max_results=200,
            )

    def _add_aob_result_to_watchlist(self, item: QListWidgetItem):
        address = int(item.text(), 16)
        name, ok = QInputDialog.getText(self, "Isim ver", "Bu AOB sonucu icin isim:")
        if not ok or not name:
            return
        vtype, ok2 = QInputDialog.getItem(
            self, "Deger tipi", "Bu adresteki deger tipi:",
            ALL_TYPES, editable=False,
        )
        if not ok2:
            vtype = "int32"
        wa = WatchedAddress(name=name, address=address, value_type=vtype)
        self.watched.append(wa)
        self._refresh_freeze_table()
        self.log(f"'{name}' (AOB) Freeze Manager'a eklendi.")

    # ------------------------------------------------------------------
    # 3) FREEZE MANAGER
    # ------------------------------------------------------------------
    def create_freeze_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        info_label = QLabel("\u26a1 Tek Is Parcacikli Freeze Scheduler Aktif (Dusuk CPU Kullanimi)")
        info_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
        layout.addWidget(info_label)

        btn_row = QHBoxLayout()
        btn_add = QPushButton("Manuel Adres Ekle")
        btn_add.clicked.connect(self._add_manual_address)
        btn_row.addWidget(btn_add)
        btn_write = QPushButton("Sec: Deger Yaz")
        btn_write.clicked.connect(self._write_value_selected)
        btn_row.addWidget(btn_write)
        btn_hotkey = QPushButton("Sec: Hotkey Ata")
        btn_hotkey.clicked.connect(self._assign_hotkey_selected)
        btn_row.addWidget(btn_hotkey)
        btn_group_hotkey = QPushButton("Coklu Sec: Ortak Hotkey (Grup Toggle)")
        btn_group_hotkey.setToolTip(
            "Ctrl/Shift ile birden fazla cheat sec, sonra buna bas:\n"
            "hepsine AYNI tus atanir, tek tusla hepsi birlikte ac/kapa olur\n"
            "(WeMod/Wand'daki profil bazli toplu hotkey davranisi)."
        )
        btn_group_hotkey.clicked.connect(self._assign_group_hotkey_selected)
        btn_row.addWidget(btn_group_hotkey)
        self.btn_pointer_scan = btn_pointer_scan = QPushButton("Sec: Pointer Zinciri Bul (Kalici Yap)")
        btn_pointer_scan.setToolTip(
            "Secili cheat'in ham adresi icin, oyun yeniden baslasa da gecerli\n"
            "kalacak bir modul+offset zinciri bulmaya calisir. AGIR bir islemdir."
        )
        btn_pointer_scan.clicked.connect(self._find_pointer_chain_for_selected)
        btn_row.addWidget(btn_pointer_scan)
        btn_change_type = QPushButton("Sec: Tip Degistir")
        btn_change_type.setToolTip(
            "Yanlis tip secilmisse (ornek: Cheat Engine'de '4 Bytes' bulup\n"
            "buraya yanlislikla 'int16' ile eklediysen) silip yeniden\n"
            "eklemene gerek yok - buradan duzeltebilirsin."
        )
        btn_change_type.clicked.connect(self._change_type_for_selected)
        btn_row.addWidget(btn_change_type)
        btn_remove = QPushButton("Sec: Sil")
        btn_remove.clicked.connect(self._remove_selected)
        btn_row.addWidget(btn_remove)
        btn_unfreeze_all = QPushButton("Tumunu Coz")
        btn_unfreeze_all.clicked.connect(self._unfreeze_all)
        btn_row.addWidget(btn_unfreeze_all)
        btn_clear_all = QPushButton("Tumunu Sil")
        btn_clear_all.setStyleSheet("background-color: #B71C1C;")
        btn_clear_all.clicked.connect(self._clear_all_watched)
        btn_row.addWidget(btn_clear_all)
        btn_save = QPushButton("Profili Kaydet")
        btn_save.clicked.connect(self._save_current_profile)
        btn_row.addWidget(btn_save)
        layout.addLayout(btn_row)

        self.freeze_table = QTableWidget(0, 5)
        self.freeze_table.setHorizontalHeaderLabels(["Dondur", "Isim", "Adres", "Tip", "Deger"])
        self.freeze_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.freeze_table.setToolTip(
            "Ipucu: 'Deger' hucresine cift tiklayip dogrudan yeni deger yazabilir, "
            "Enter'a basabilirsin - ayri bir pencere acmana gerek yok."
        )
        self.freeze_table.itemChanged.connect(self._on_freeze_item_changed)
        self.freeze_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.freeze_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        layout.addWidget(self.freeze_table)
        return widget

    def _selected_watched_index(self) -> Optional[int]:
        row = self.freeze_table.currentRow()
        if row is None or row < 0 or row >= len(self.watched):
            return None
        return row

    def _resolve_wa_address(self, wa: WatchedAddress) -> Optional[int]:
        """
        Bir WatchedAddress'in GERCEK bellek adresini dondurur.
        - offsets doluysa (kalici pointer zinciri): her seferinde YENIDEN
          cozulur (pointer'in gosterdigi yer oyun calisirken degisebilir,
          bu yuzden onbelleklemek yanlis olur). Basarili olursa wa.address
          sadece GORUNTULEME icin guncellenir.
        - offsets boşsa: ham (session'a ozel) adres dogrudan kullanilir.

        ONCEKI EKSIK: profil offsets ile yuklendiginde ama ham 'address'
        alani 0 oldugunda (baska bir bilgisayardan ice aktarilan profil
        gibi), eskiden hicbir yerde offsets cozulmuyordu - bu tur kalici
        profiller sessizce hicbir sey yapmiyordu. Artik bu fonksiyon her
        okuma/yazmadan once cagriliyor.
        """
        if wa.offsets:
            if not self.engine.attached:
                return None
            try:
                addr = self.engine.resolve_pointer_chain(wa.offsets)
                wa.address = addr
                return addr
            except Exception:
                return None
        return wa.address if wa.address else None

    def _add_manual_address(self):
        if not self._require_attached():
            return
        addr_str, ok = QInputDialog.getText(self, "Adres", "Hex adres gir (ornek: 0x1A2B3C4D):")
        if not ok or not addr_str:
            return
        try:
            address = int(addr_str, 16)
        except ValueError:
            QMessageBox.warning(self, "Uyari", "Gecersiz hex adres.")
            return
        name, ok2 = QInputDialog.getText(self, "Isim", "Bu cheat icin isim:")
        if not ok2 or not name:
            name = "Isimsiz"
        vtype, ok3 = QInputDialog.getItem(
            self, "Deger tipi", "Tip:",
            ALL_TYPES, editable=False,
        )
        if not ok3:
            vtype = "int32"
        self.watched.append(WatchedAddress(name=name, address=address, value_type=vtype))
        self._refresh_freeze_table()

    def _write_value_selected(self):
        idx = self._selected_watched_index()
        if idx is None:
            QMessageBox.information(self, "Bilgi", "Once listeden bir satir sec.")
            return
        wa = self.watched[idx]
        raw, ok = QInputDialog.getText(self, "Yeni deger", f"'{wa.name}' icin yeni deger:")
        if not ok:
            return
        addr = self._resolve_wa_address(wa)
        if addr is None:
            QMessageBox.warning(self, "Uyari", "Bu cheat'in adresi cozulemedi (pointer zinciri gecersiz olabilir).")
            return
        try:
            value = float(raw) if wa.value_type in ("float", "double") else int(raw)
            self.engine.write_value(addr, wa.value_type, value)
            if wa.frozen:
                wa.frozen_value = value
        except Exception as e:
            QMessageBox.critical(self, "Hata", f"Yazilamadi:\n{e}")
        self._refresh_freeze_table()

    def _assign_hotkey_selected(self):
        idx = self._selected_watched_index()
        if idx is None:
            QMessageBox.information(self, "Bilgi", "Once listeden bir satir sec.")
            return
        wa = self.watched[idx]
        hk, ok = QInputDialog.getText(self, "Hotkey", "Tus kombinasyonu (ornek: f1, ctrl+f2):")
        if not ok or not hk:
            return
        if wa.hotkey:
            # Eski hotkey'i sadece BU cheat icin kayittan sil (owner_id ile) -
            # ayni tusu paylasan baska bir cheat varsa onu etkilemez.
            self.hotkeys.unregister(wa.hotkey, owner_id=id(wa))
        wa.hotkey = hk.strip()
        self._bind_hotkey(wa)
        self._refresh_freeze_table()

    def _assign_group_hotkey_selected(self):
        """Secili BIRDEN FAZLA cheat'e AYNI hotkey'i atar (WeMod/Wand'daki
        gibi tek tusla bir grup cheat'i topluca ac/kapa). Her cheat kendi
        frozen durumunu ayri ayri tutar, ama hepsi ayni tus basisinda
        birlikte tetiklenir."""
        rows = sorted({idx.row() for idx in self.freeze_table.selectedIndexes()})
        rows = [r for r in rows if 0 <= r < len(self.watched)]
        if len(rows) < 2:
            QMessageBox.information(
                self, "Bilgi",
                "Bu, birden fazla cheat'e AYNI tusu atamak icindir - "
                "Ctrl/Shift ile en az 2 satir sec."
            )
            return
        hk, ok = QInputDialog.getText(
            self, "Grup Hotkey",
            f"{len(rows)} cheat icin ortak tus kombinasyonu (ornek: f1, ctrl+f2):"
        )
        if not ok or not hk:
            return
        hk = hk.strip()
        for r in rows:
            wa = self.watched[r]
            if wa.hotkey:
                self.hotkeys.unregister(wa.hotkey, owner_id=id(wa))
            wa.hotkey = hk
            self._bind_hotkey(wa)
        self._refresh_freeze_table()
        self.log(f"{len(rows)} cheat'e ortak grup hotkey ({hk}) atandi - tek tusla hepsi birlikte ac/kapa olacak.")

    def _find_pointer_chain_for_selected(self):
        idx = self._selected_watched_index()
        if idx is None:
            QMessageBox.information(self, "Bilgi", "Once listeden bir satir sec.")
            return
        wa = self.watched[idx]
        if wa.offsets:
            QMessageBox.information(self, "Bilgi", f"'{wa.name}' zaten kalici bir pointer zincirine sahip.")
            return
        if not wa.address:
            QMessageBox.warning(self, "Uyari", "Bu cheat'in ham bir adresi yok, pointer scan yapilamaz.")
            return
        if not self._require_attached():
            return

        choice, ok = QInputDialog.getItem(
            self, "Tarama Derinligi",
            "Hizli: sadece dogrudan (statik) pointer'lari arar, saniyeler surer.\n"
            "Detayli: 2 seviyeli arar (daha fazla sonuc bulabilir) ama HER aday\n"
            "icin tum bellegi tekrar tarar - buyuk oyunlarda dakikalar surebilir.",
            ["Hizli (1 seviye)", "Detayli (2 seviye, cok yavas)"], editable=False,
        )
        if not ok:
            return
        max_level = 1 if choice.startswith("Hizli") else 2

        def on_success(chains):
            self.status_bar.showMessage("Hazir.")
            if not chains:
                QMessageBox.information(
                    self, "Sonuc Yok",
                    "Bu adres icin kalici bir pointer zinciri bulunamadi.\n"
                    "Cheat Engine'de manuel pointer scan yapman gerekebilir."
                )
                return
            labels = [f"{i+1}) offsets={chain}" for i, chain in enumerate(chains[:50])]
            label, ok2 = QInputDialog.getItem(
                self, "Pointer Zinciri Sec",
                f"{len(chains)} aday bulundu (en fazla 50 gosteriliyor). "
                "Birini sec (ilk siradaki genelde en guvenilir):",
                labels, editable=False,
            )
            if not ok2:
                return
            chosen_idx = labels.index(label)
            wa.offsets = chains[chosen_idx]
            self.log(f"'{wa.name}' icin kalici pointer zinciri atandi: {wa.offsets}")
            self._refresh_freeze_table()
            QMessageBox.information(
                self, "Basarili",
                f"'{wa.name}' artik kalici bir pointer zinciri kullaniyor.\n"
                "Bunu koru diye 'Profili Kaydet'e basmayi unutma."
            )

        self._run_scan_in_background(
            "Pointer zinciri araniyor (arayuz yanit vermeye devam edecek)...",
            self.engine.find_pointers_to, on_success, wa.address, max_level=max_level,
        )

    def _change_type_for_selected(self):
        """
        Var olan bir cheat'in deger tipini degistirir (silip yeniden
        eklemeye gerek kalmadan). Ozellikle Cheat Engine'de '4 Bytes'
        (int32) olarak bulunup buraya yanlislikla farkli bir tiple
        (ornek: int16) eklenmis adresleri duzeltmek icin kullanislidir.
        """
        idx = self._selected_watched_index()
        if idx is None:
            QMessageBox.information(self, "Bilgi", "Once listeden bir satir sec.")
            return
        wa = self.watched[idx]
        current_index = ALL_TYPES.index(wa.value_type) if wa.value_type in ALL_TYPES else 0
        new_type, ok = QInputDialog.getItem(
            self, "Tip Degistir",
            f"'{wa.name}' icin dogru tipi sec (Cheat Engine 'X Bytes' gosteriyorsa: "
            "4 Bytes=int32, 8 Bytes=int64, 2 Bytes=int16, 1 Byte=byte):",
            ALL_TYPES, current=current_index, editable=False,
        )
        if not ok or new_type == wa.value_type:
            return
        wa.value_type = new_type
        self.log(f"'{wa.name}' tipi degistirildi -> {new_type}")
        self._refresh_freeze_table()

    def _bind_hotkey(self, wa: WatchedAddress):
        if not wa.hotkey:
            return

        def callback():
            wa.frozen = not wa.frozen
            if wa.frozen:
                addr = self._resolve_wa_address(wa)
                if addr is not None:
                    try:
                        wa.frozen_value = self.engine.read_value(addr, wa.value_type)
                    except Exception:
                        pass
            self.log(f"Hotkey ({wa.hotkey}): {wa.name} -> {'DONDU' if wa.frozen else 'cozuldu'}")

        try:
            self.hotkeys.register(wa.hotkey, callback, owner_id=id(wa))
        except Exception as e:
            QMessageBox.warning(self, "Uyari", f"Hotkey atanamadi ({wa.hotkey}):\n{e}")

    def _remove_selected(self):
        idx = self._selected_watched_index()
        if idx is None:
            return
        wa = self.watched[idx]
        if wa.hotkey:
            self.hotkeys.unregister(wa.hotkey, owner_id=id(wa))
        del self.watched[idx]
        self._refresh_freeze_table()

    def _unfreeze_all(self):
        for wa in self.watched:
            wa.frozen = False
        self._refresh_freeze_table()
        self.log("Tum adreslerin dondurulmasi kaldirildi.")

    def _clear_all_watched(self):
        if not self.watched:
            return
        reply = QMessageBox.question(
            self, "Emin misin?",
            f"{len(self.watched)} cheat listeden silinecek. Devam edilsin mi?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        self.hotkeys.unregister_all()
        self.watched.clear()
        self._refresh_freeze_table()
        self.log("Freeze Manager listesi temizlendi.")

    def _on_freeze_checkbox_toggled(self, row: int, checked: bool):
        if row >= len(self.watched):
            return
        wa = self.watched[row]
        wa.frozen = checked
        if wa.frozen:
            addr = self._resolve_wa_address(wa)
            if addr is not None:
                try:
                    wa.frozen_value = self.engine.read_value(addr, wa.value_type)
                except Exception:
                    pass

    def _refresh_freeze_table(self):
        """Tam yeniden cizim - yapisal degisikliklerde (ekleme/silme/profil
        yukleme) cagrilir. Secili satiri korur."""
        selected_row = self.freeze_table.currentRow()

        self.freeze_table.blockSignals(True)  # itemChanged'in kendini tetiklemesini engelle
        self.freeze_table.setRowCount(0)
        for i, wa in enumerate(self.watched):
            row = self.freeze_table.rowCount()
            self.freeze_table.insertRow(row)
            self.freeze_table.setRowHeight(row, 32)

            chk = ToggleSwitch()
            chk.set_checked_instant(wa.frozen)
            chk.setEnabled(self.engine.attached)
            chk.toggled.connect(lambda checked, r=row: self._on_freeze_checkbox_toggled(r, checked))
            # Hucreye ortalanmis sekilde yerlestir (WeMod tarzi - satirin
            # tam ortasinda, kenarlara yapismadan).
            cell = QWidget()
            cell_layout = QHBoxLayout(cell)
            cell_layout.addWidget(chk)
            cell_layout.setAlignment(Qt.AlignCenter)
            cell_layout.setContentsMargins(0, 0, 0, 0)
            self.freeze_table.setCellWidget(row, 0, cell)

            name_item = QTableWidgetItem(wa.name)
            name_item.setFlags(name_item.flags() & ~Qt.ItemIsEditable)
            self.freeze_table.setItem(row, 1, name_item)

            resolved_addr = self._resolve_wa_address(wa)
            addr_label = hex(resolved_addr) if resolved_addr else (
                "(cozulemedi)" if wa.offsets else "(offset zinciri)"
            )
            addr_item = QTableWidgetItem(addr_label)
            addr_item.setFlags(addr_item.flags() & ~Qt.ItemIsEditable)
            self.freeze_table.setItem(row, 2, addr_item)

            type_item = QTableWidgetItem(wa.value_type)
            type_item.setFlags(type_item.flags() & ~Qt.ItemIsEditable)
            self.freeze_table.setItem(row, 3, type_item)

            live_value = ""
            if self.engine.attached and resolved_addr:
                try:
                    live_value = str(self.engine.read_value(resolved_addr, wa.value_type))
                except Exception:
                    live_value = "?"
            # SADECE Deger sutunu (4) duzenlenebilir - cift tikla, yaz, Enter'a
            # bas, dogrudan bellege yazilir (ayri dialog acmaya gerek yok).
            self.freeze_table.setItem(row, 4, QTableWidgetItem(live_value))

        self.freeze_table.blockSignals(False)
        if 0 <= selected_row < self.freeze_table.rowCount():
            self.freeze_table.selectRow(selected_row)

    def _on_freeze_item_changed(self, item: QTableWidgetItem):
        """
        Kullanici Freeze Manager tablosunda 'Deger' hucresini elle
        duzenleyip Enter'a basinca tetiklenir. blockSignals() sayesinde
        bizim programatik guncellemelerimiz bunu tetiklemez - sadece
        GERCEK kullanici duzenlemesi buraya duser.
        """
        if item.column() != 4:
            return
        row = item.row()
        if row >= len(self.watched):
            return
        wa = self.watched[row]
        if not self.engine.attached:
            return
        addr = self._resolve_wa_address(wa)
        if addr is None:
            QMessageBox.warning(self, "Uyari", "Bu cheat'in adresi cozulemedi (pointer zinciri gecersiz olabilir).")
            self._refresh_freeze_table()
            return
        raw = item.text().strip()
        try:
            value = float(raw) if wa.value_type in ("float", "double") else int(raw)
            self.engine.write_value(addr, wa.value_type, value)
            if wa.frozen:
                wa.frozen_value = value
            self.log(f"'{wa.name}' degeri tablodan duzenlendi -> {value}")
        except Exception as e:
            QMessageBox.warning(self, "Uyari", f"Deger yazilamadi:\n{e}")
            self._refresh_freeze_table()  # eski gecerli degere geri don

    def _update_freeze_values_only(self):
        """
        Hafif guncelleme - arka plan QTimer (her ~500ms) bunu cagirir.
        ONCEKI HATA: eskiden tick her seferinde _refresh_freeze_table()
        cagiriyordu; bu tum satirlari/checkbox widget'larini yeniden
        olusturuyor ve kullanicinin sectigi satiri surekli sifirliyordu -
        bu yuzden 'Sec: Deger Yaz/Hotkey Ata/Sil' butonlari pratikte
        kullanilamiyordu (tikla -> secim kayboluyor). Bu fonksiyon sadece
        Deger sutununu gunceller, satir/checkbox/secimi bozmaz.

        blockSignals kullaniyoruz ki bu OTOMATIK guncelleme, kullanicinin
        az once elle yazdigi degeri "duzenleme" olarak algilayip
        _on_freeze_item_changed'i tetiklemesin.
        """
        if self.freeze_table.rowCount() != len(self.watched):
            self._refresh_freeze_table()
            return
        self.freeze_table.blockSignals(True)
        for row, wa in enumerate(self.watched):
            live_value = ""
            addr = self._resolve_wa_address(wa) if self.engine.attached else None
            if addr:
                try:
                    live_value = str(self.engine.read_value(addr, wa.value_type))
                except Exception:
                    live_value = "?"
            item = self.freeze_table.item(row, 4)
            if item is None:
                self.freeze_table.setItem(row, 4, QTableWidgetItem(live_value))
            elif item.text() != live_value:
                item.setText(live_value)
        self.freeze_table.blockSignals(False)

    def _save_current_profile(self):
        if not self.engine.process_name:
            QMessageBox.warning(self, "Uyari", "Once bir process'e baglan.")
            return
        label, ok = QInputDialog.getText(
            self, "Oyun adi", "Bu profil icin isim (ornek: Palworld v1.0+48):",
            text=self.current_game_label or self.engine.process_name,
        )
        if not ok or not label:
            return
        save_profile(self.engine.process_name, label, self.watched)
        self.log(f"Profil kaydedildi: {label}")
        self.status_bar.showMessage(f"Profil kaydedildi: {label}")
        self._refresh_profile_combo()

    # ------------------------------------------------------------------
    # 4) DISASM & PATCH (UNDO)
    # ------------------------------------------------------------------
    def create_patch_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        patch_box = QGroupBox("Memory Patcher (Restore Destekli)")
        p_layout = QVBoxLayout(patch_box)

        r1 = QHBoxLayout()
        r1.addWidget(QLabel("Adres (hex):"))
        self.patch_addr_edit = QLineEdit(placeholderText="0x1A2B3C4D")
        r1.addWidget(self.patch_addr_edit)
        r1.addWidget(QLabel("Yeni Bytelar (hex, bosluklu):"))
        self.patch_bytes_edit = QLineEdit(placeholderText="90 90 90")
        r1.addWidget(self.patch_bytes_edit)
        p_layout.addLayout(r1)

        r3 = QHBoxLayout()
        btn_patch = QPushButton("Patch Uygula (Inject)")
        btn_patch.clicked.connect(self._apply_patch)
        btn_nop = QPushButton("Hizli NOP Doldur")
        btn_nop.setToolTip("Yeni Bytelar kutusunu yoksayar, Adres'ten itibaren N byte'i 0x90 (NOP) ile doldurur.")
        btn_nop.clicked.connect(self._apply_nop_fill)
        btn_undo = QPushButton("Geri Al (Restore Original Bytes)")
        btn_undo.setStyleSheet("background-color: #B71C1C; color: white;")
        btn_undo.clicked.connect(self._undo_patch)
        r3.addWidget(btn_patch)
        r3.addWidget(btn_nop)
        r3.addWidget(btn_undo)
        p_layout.addLayout(r3)

        self.patch_list = QListWidget()
        p_layout.addWidget(QLabel("Uygulanan patchler (adres -> orijinal bytelar):"))
        p_layout.addWidget(self.patch_list)

        layout.addWidget(patch_box)
        layout.addStretch()
        return widget

    def _apply_patch(self):
        if not self._require_attached():
            return
        try:
            address = int(self.patch_addr_edit.text().strip(), 16)
        except ValueError:
            QMessageBox.warning(self, "Uyari", "Gecersiz hex adres.")
            return
        try:
            new_bytes = bytes(int(b, 16) for b in self.patch_bytes_edit.text().split())
        except ValueError:
            QMessageBox.warning(self, "Uyari", "Gecersiz byte listesi (ornek: 90 90 90).")
            return
        if not new_bytes:
            QMessageBox.warning(self, "Uyari", "En az bir byte gir.")
            return
        try:
            original = self.engine.apply_byte_patch(address, new_bytes)
        except Exception as e:
            QMessageBox.critical(self, "Hata", f"Patch uygulanamadi:\n{e}")
            return
        self.byte_patches[address] = original
        self.patch_list.addItem(f"{hex(address)} -> orijinal: {original.hex(' ')}")
        self.log(f"Patch uygulandi: {hex(address)} ({len(new_bytes)} byte)")

    def _apply_nop_fill(self):
        if not self._require_attached():
            return
        try:
            address = int(self.patch_addr_edit.text().strip(), 16)
        except ValueError:
            QMessageBox.warning(self, "Uyari", "Gecersiz hex adres.")
            return
        length, ok = QInputDialog.getInt(self, "NOP uzunlugu", "Kac byte NOP (0x90) ile doldurulsun?", 2, 1, 64)
        if not ok:
            return
        try:
            original = self.engine.nop_fill(address, length)
        except Exception as e:
            QMessageBox.critical(self, "Hata", f"NOP doldurulamadi:\n{e}")
            return
        self.byte_patches[address] = original
        self.patch_list.addItem(f"{hex(address)} -> orijinal: {original.hex(' ')}")
        self.log(f"NOP doldurma uygulandi: {hex(address)} ({length} byte)")

    def _undo_patch(self):
        selected = self.patch_list.currentItem()
        if not selected:
            QMessageBox.information(self, "Bilgi", "Listeden geri alinacak bir patch sec.")
            return
        addr_str = selected.text().split(" -> ")[0]
        address = int(addr_str, 16)
        original = self.byte_patches.get(address)
        if original is None:
            QMessageBox.warning(self, "Uyari", "Bu adres icin orijinal deger bulunamadi.")
            return
        try:
            self.engine.restore_byte_patch(address, original)
        except Exception as e:
            QMessageBox.critical(self, "Hata", f"Geri alinamadi:\n{e}")
            return
        del self.byte_patches[address]
        self.patch_list.takeItem(self.patch_list.row(selected))
        self.log(f"Patch geri alindi: {hex(address)}")

    # ------------------------------------------------------------------
    # 5) SCRIPT ENGINE
    # ------------------------------------------------------------------
    def create_script_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.addWidget(QLabel(
            "Kisitli Script Motoru (guvenlik icin sadece asagidaki komutlari destekler):\n"
            "  isim = ScanPattern('A1 ?? ?? ?? ??')   |   Freeze(isim, deger)\n"
            "  Write(isim, deger)                      |   Log('mesaj')"
        ))

        self.script_editor = QTextEdit()
        self.script_editor.setPlaceholderText(
            "-- Ornek Script\n"
            "HealthAddr = ScanPattern('A1 ?? ?? ?? ?? 8B 45 FC')\n"
            "Freeze(HealthAddr, 999)\n"
            "Log('Can dondu')"
        )
        layout.addWidget(self.script_editor)

        btn_layout = QHBoxLayout()
        btn_run = QPushButton("Calistir (Execute)")
        btn_run.clicked.connect(self._run_script)
        btn_layout.addWidget(btn_run)
        layout.addLayout(btn_layout)
        return widget

    def _run_script(self):
        if not self._require_attached():
            return
        text = self.script_editor.toPlainText()
        try:
            self.script_engine.run(text)
        except ScriptError as e:
            QMessageBox.critical(self, "Script Hatasi", str(e))
            return
        self.log("Script calistirildi.")

    # ------------------------------------------------------------------
    # 6) GUNCELLEME
    # ------------------------------------------------------------------
    def create_update_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        appearance_box = QGroupBox("Gorunum")
        appearance_v = QHBoxLayout(appearance_box)
        appearance_v.addWidget(QLabel("Tema:"))
        self.theme_combo = QComboBox()
        self._theme_keys = list(themes.THEMES.keys())
        for key in self._theme_keys:
            self.theme_combo.addItem(themes.THEME_LABELS.get(key, key))
        if self.current_theme in self._theme_keys:
            self.theme_combo.setCurrentIndex(self._theme_keys.index(self.current_theme))
        self.theme_combo.currentIndexChanged.connect(
            lambda i: self._change_theme(self._theme_keys[i])
        )
        appearance_v.addWidget(self.theme_combo)
        appearance_v.addStretch(1)
        layout.addWidget(appearance_box)

        info_box = QGroupBox("Surum Bilgisi")
        info_v = QVBoxLayout(info_box)
        info_v.addWidget(QLabel(f"Mevcut surum: {updater.CURRENT_VERSION}"))
        info_v.addWidget(QLabel(
            "Otomatik guncelleme icin bir 'manifest' JSON dosyasi barindirman\n"
            "gerekir (ornek: GitHub'da ucretsiz bir repo + raw dosya linki).\n"
            "Manifest ornegi icin proje icindeki update_manifest_example.json'a bak."
        ))
        layout.addWidget(info_box)

        settings_box = QGroupBox("Ayarlar")
        settings_v = QVBoxLayout(settings_box)
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Manifest URL:"))
        self.manifest_url_edit = QLineEdit(self.app_config.get("update_manifest_url", ""))
        self.manifest_url_edit.setPlaceholderText(
            "https://raw.githubusercontent.com/kullanici/repo/main/update_manifest.json"
        )
        row1.addWidget(self.manifest_url_edit)
        btn_save_url = QPushButton("Kaydet")
        btn_save_url.clicked.connect(self._save_update_settings)
        row1.addWidget(btn_save_url)
        settings_v.addLayout(row1)

        self.auto_check_box = QCheckBox("Baslangicta otomatik kontrol et")
        self.auto_check_box.setChecked(self.app_config.get("auto_check_updates", True))
        self.auto_check_box.stateChanged.connect(self._save_update_settings)
        settings_v.addWidget(self.auto_check_box)
        layout.addWidget(settings_box)

        action_box = QGroupBox("Durum")
        action_v = QVBoxLayout(action_box)
        btn_row = QHBoxLayout()
        btn_check = QPushButton("Guncellemeleri Kontrol Et")
        btn_check.clicked.connect(lambda: self._check_for_updates(silent=False))
        btn_row.addWidget(btn_check)
        self.btn_do_update = QPushButton("Simdi Guncelle")
        self.btn_do_update.setEnabled(False)
        self.btn_do_update.setStyleSheet("background-color: #2e7d32;")
        self.btn_do_update.clicked.connect(self._download_and_apply_update)
        btn_row.addWidget(self.btn_do_update)
        action_v.addLayout(btn_row)

        self.update_status_label = QLabel("Henuz kontrol edilmedi.")
        action_v.addWidget(self.update_status_label)
        self.update_progress = QProgressBar()
        self.update_progress.setVisible(False)
        action_v.addWidget(self.update_progress)
        self.update_changelog = QTextEdit()
        self.update_changelog.setReadOnly(True)
        self.update_changelog.setMaximumHeight(120)
        action_v.addWidget(self.update_changelog)
        layout.addWidget(action_box)
        layout.addStretch()
        return widget

    def _save_update_settings(self, *_args):
        self.app_config["update_manifest_url"] = self.manifest_url_edit.text().strip()
        self.app_config["auto_check_updates"] = self.auto_check_box.isChecked()
        config_manager.save_config(self.app_config)

    def _check_for_updates(self, silent: bool = False):
        manifest_url = (self.manifest_url_edit.text().strip()
                        if hasattr(self, "manifest_url_edit")
                        else self.app_config.get("update_manifest_url", ""))
        if not manifest_url:
            if not silent:
                QMessageBox.information(
                    self, "Bilgi",
                    "Once 'Ayarlar' altina bir manifest URL'i gir ve Kaydet'e bas.\n"
                    "(README'deki 'Otomatik Guncelleme Kurulumu' bolumune bak.)"
                )
            return
        if self.update_worker and self.update_worker.isRunning():
            return
        if hasattr(self, "update_status_label"):
            self.update_status_label.setText("Kontrol ediliyor...")
        self.update_worker = UpdateCheckWorker(mode="check", manifest_url=manifest_url)
        self.update_worker.check_finished.connect(lambda info: self._on_update_check_finished(info, silent))
        self.update_worker.check_error.connect(lambda err: self._on_update_check_error(err, silent))
        self.update_worker.start()

    def _on_update_check_finished(self, info, silent: bool):
        self.pending_update = info
        if info is None:
            msg = f"Guncel: en son surumu kullaniyorsun (v{updater.CURRENT_VERSION})."
            if hasattr(self, "update_status_label"):
                self.update_status_label.setText(msg)
            if hasattr(self, "btn_do_update"):
                self.btn_do_update.setEnabled(False)
            if not silent:
                self.log(msg)
            return
        msg = f"Yeni surum bulundu: v{info.version} (senin surumun: v{updater.CURRENT_VERSION})"
        self.log(msg)
        if hasattr(self, "update_status_label"):
            self.update_status_label.setText(msg)
        if hasattr(self, "update_changelog"):
            self.update_changelog.setPlainText(info.changelog or "(degisiklik notu yok)")
        if hasattr(self, "btn_do_update"):
            self.btn_do_update.setEnabled(True)
        if silent:
            QMessageBox.information(
                self, "Guncelleme Mevcut",
                f"Yeni bir surum var: v{info.version}\n\n{info.changelog}\n\n"
                "'Guncelleme' sekmesinden indirip kurabilirsin."
            )

    def _on_update_check_error(self, error_msg: str, silent: bool):
        if hasattr(self, "update_status_label"):
            self.update_status_label.setText(f"Kontrol edilemedi: {error_msg}")
        # Sessiz (baslangic) kontrolde kullaniciyi rahatsiz etme, sadece logla.
        self.log(f"Guncelleme kontrolu basarisiz: {error_msg}")
        if not silent:
            QMessageBox.warning(self, "Hata", f"Guncelleme kontrol edilemedi:\n{error_msg}")

    def _download_and_apply_update(self):
        if not self.pending_update:
            return
        # ESKI (installer=False) yontem sadece derlenmis .exe halinde
        # calisir (kendi uzerine kopyalama gerektirir). Installer=True
        # oldugunda (GitHub Actions pipeline'inin urettigi Setup.exe)
        # bu kisitlama YOK - indirilen kurulum dosyasi bagimsiz calisir.
        if not self.pending_update.installer and not updater.is_frozen():
            QMessageBox.information(
                self, "Bilgi",
                "Su an kaynak koddan (python main.py) calisiyorsun. Otomatik\n"
                "dosya degistirme sadece derlenmis .exe halinde desteklenir.\n\n"
                f"Yeni surumu su adresten indirebilirsin:\n{self.pending_update.download_url}"
            )
            return
        self.update_progress.setVisible(True)
        self.update_progress.setValue(0)
        self.btn_do_update.setEnabled(False)
        self.update_worker = UpdateCheckWorker(mode="download", update_info=self.pending_update)
        self.update_worker.download_progress.connect(self._on_download_progress)
        self.update_worker.download_finished.connect(self._on_download_finished)
        self.update_worker.download_error.connect(self._on_download_error)
        self.update_worker.start()

    def _on_download_progress(self, downloaded: int, total: int):
        if total > 0:
            self.update_progress.setValue(int(downloaded * 100 / total))

    def _on_download_finished(self, path: str):
        self.update_progress.setVisible(False)
        is_installer = bool(self.pending_update and self.pending_update.installer)
        if is_installer:
            question = (
                "Yeni surum indirildi ve dogrulandi. Kurulum sessizce\n"
                "calistirilacak; islem bitince uygulama otomatik olarak\n"
                "yeniden acilacak. Devam edilsin mi?"
            )
        else:
            question = (
                "Yeni surum indirildi ve dogrulandi. Uygulama simdi kapanip\n"
                "yeniden baslatilacak. Devam edilsin mi?"
            )
        reply = QMessageBox.question(
            self, "Guncelleme Hazir", question, QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            self.btn_do_update.setEnabled(True)
            return
        try:
            if is_installer:
                updater.apply_installer_update(path, self.pending_update.silent_args)
            else:
                updater.apply_update_and_restart(path)
        except Exception as e:
            QMessageBox.critical(self, "Hata", f"Guncelleme uygulanamadi:\n{e}")
            self.btn_do_update.setEnabled(True)
            return
        self.hotkeys.unregister_all()
        self.engine.detach()
        QApplication.quit()

    def _on_download_error(self, error_msg: str):
        self.update_progress.setVisible(False)
        self.btn_do_update.setEnabled(True)
        QMessageBox.critical(self, "Hata", f"Guncelleme indirilemedi:\n{error_msg}")
        self.log(f"Guncelleme indirme hatasi: {error_msg}")

    # ------------------------------------------------------------------
    # ARKA PLAN DONGUSU
    # ------------------------------------------------------------------
    def _tick(self):
        if not self.engine.attached:
            return
        # Oyun kapatildiysa (process artik yok) otomatik olarak baglantiyi
        # kes ve kullaniciya bildir - aksi halde sessizce bos yere yazma
        # denemeye devam ederdik.
        if not self.engine.is_process_alive():
            self.log(f"'{self.engine.process_name}' artik calismiyor - baglanti otomatik kesildi.")
            self._detach()
            return

        for wa in self.watched:
            if wa.frozen and wa.frozen_value is not None:
                addr = self._resolve_wa_address(wa)
                if addr is not None:
                    try:
                        self.engine.write_value(addr, wa.value_type, wa.frozen_value)
                    except Exception:
                        pass
        self.script_engine.apply_frozen()
        self._update_freeze_values_only()

    # ------------------------------------------------------------------
    def apply_theme(self, theme_key: str = None):
        """Secilen temanin paletiyle stylesheet'i uretip uygular. theme_key
        verilmezse mevcut self.current_theme kullanilir (baslangicta
        config'ten yuklenen ya da en son secilen tema)."""
        if theme_key is not None:
            self.current_theme = theme_key
        self.setStyleSheet(themes.build_stylesheet(self.current_theme))

    def _change_theme(self, theme_key: str):
        self.apply_theme(theme_key)
        self.app_config["theme"] = theme_key
        config_manager.save_config(self.app_config)
        self.log(f"Tema degistirildi: {themes.THEME_LABELS.get(theme_key, theme_key)}")

    def closeEvent(self, event):
        self.hotkeys.unregister_all()
        self.engine.detach()
        event.accept()


if __name__ == '__main__':
    # PyInstaller ile derlenmis (.exe) frozen halde multiprocessing
    # kullanildiginda ZORUNLU: bu cagri olmadan, Windows'ta her yeni
    # worker process TUM programi (QApplication dahil) bastan
    # calistirmaya calisir - sonsuz pencere/process acilmasina yol
    # acar. freeze_support() bunu tespit edip worker process'lerin
    # sadece atanan is'i yapip cikmasini saglar. GUI baslamadan ONCE,
    # en basta cagrilmali.
    multiprocessing.freeze_support()
    app = QApplication(sys.argv)
    window = LocalTrainerStudio()
    window.show()
    sys.exit(app.exec_())
