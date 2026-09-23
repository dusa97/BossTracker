# Build: run build.bat, or: pyinstaller --onefile --noconsole --noupx --name BossTracker --icon=icon.ico main.py
import copy
import ctypes
from ctypes import wintypes
import functools
import io
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta
import numpy as np
from PIL import Image, ImageEnhance
from PyQt6.QtCore import (
    Qt, QMimeData, QTimer, QPoint, QEvent, QRect, QSize, QThread, pyqtSignal,
    QBuffer, QIODevice,
)
from PyQt6.QtGui import QDrag, QPixmap, QPainter, QColor, QIcon, QLinearGradient, QFont
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLabel, QScrollArea, QFrame, QPushButton, QInputDialog,
    QStackedWidget, QTableWidget, QTableWidgetItem, QHeaderView, QCalendarWidget,
    QDialog, QDialogButtonBox, QMessageBox, QTabWidget, QListWidget, QCheckBox,
    QComboBox, QSpinBox, QLineEdit, QFileDialog, QPlainTextEdit
)

if getattr(sys, 'frozen', False):
    _BASE_DIR = os.path.dirname(sys.executable)
else:
    _BASE_DIR = os.path.dirname(os.path.abspath(__file__))

ITEMS_ASSETS_DIR  = os.path.join(_BASE_DIR, "assets")
BOSS_ASSETS_DIR   = os.path.join(_BASE_DIR, "boss")
SOURCES_ASSETS_DIR = os.path.join(_BASE_DIR, "sources")
DATA_FILE        = os.path.join(_BASE_DIR, "boss_tracker_data.json")
_BM_PATH = os.path.join(BOSS_ASSETS_DIR, "BlackMage.png")
NUM_WEEKS_TO_SHOW = 4
APP_VERSION = "v1.30"

# Item Scanner (F9 tooltip capture/OCR) is built but hidden from the UI for now — flip to True
# to bring back the tab and the F9 global hotkey. Nothing else needs to change.
ENABLE_ITEM_SCANNER = False

# --- Boss difficulty tiers with 1-member crystal meso values ---
BOSS_DIFFICULTY_MAP = {
    "cygnus":    {"Easy":      45_562_500, "Normal":    72_250_000},
    "hilla":     {"Hard":     56_250_000},
    "pink bean": {"Chaos":    64_000_000},
    "zakum":     {"Chaos":    81_000_000},
    "pierre":    {"Chaos":    81_000_000},
    "von bon":   {"Chaos":    81_000_000},
    "crimson queen": {"Chaos": 81_000_000},
    "princess no":   {"Normal": 81_000_000},
    "magnus":    {"Hard":     95_062_500},
    "vellum":    {"Chaos":   105_062_500},
    "papulatus": {"Chaos":   132_250_000},
    "akechi mitsuhide": {"Normal": 144_000_000},
    "damien":    {"Normal":   169_000_000, "Hard":    421_875_000},
    "lotus":     {"Normal":    32_512_500, "Hard":    444_675_000, "Extreme":  1_397_500_000},
    "kalos":     {"Easy":     937_500_000, "Normal": 1_300_000_000, "Chaos":  2_600_000_000, "Extreme": 5_200_000_000},
    "kaling":    {"Easy":   1_031_250_000, "Normal": 1_506_500_000, "Hard":   2_990_000_000, "Extreme": 6_026_000_000},
    "gloom":     {"Normal":   297_675_000, "Chaos":    563_945_000},
    "darknell":  {"Normal":   316_875_000, "Hard":     667_920_000},
    "lucid":     {"Easy":     237_009_375, "Normal":   253_828_125, "Hard":     504_000_000},
    "will":      {"Easy":     246_744_750, "Normal":   279_075_000, "Hard":     621_810_000},
    "seren":     {"Normal":   889_021_875, "Hard":   1_096_560_000, "Extreme": 4_235_000_000},
    "vhilla":    {"Normal":   581_880_000, "Hard":     762_105_000},
    "limbo":     {"Normal": 2_100_000_000, "Hard":   3_745_000_000},
    "baldrix":   {"Normal": 2_800_000_000, "Hard":   4_200_000_000},
    "blackmage": {"Hard":   4_500_000_000, "Extreme": 18_000_000_000},
    "first adversary": {"Easy": 985_000_000, "Normal": 1_365_000_000, "Hard": 2_940_000_000, "Extreme": 5_880_000_000},
    "guardian angel slime": {"Normal": 231_673_500, "Chaos": 654_578_125},
    "malefic star": {"Normal": 1_452_000_000, "Hard": 3_990_000_000},
    "jupiter":   {"Normal": 2_965_000_000, "Hard": 5_953_000_000},
}

MONTHLY_BOSSES = {"blackmage"}

# Items whose loot icon has only a 2-way left-click toggle instead of the normal
# 3-way state cycle: click once to stamp the mapped overlay icon on top (e.g. the
# ring box was converted into its grindstone), click again to go back to plain.
SPECIAL_ITEM_OVERLAYS = {
    "life boss ring box": "Grindstone of Life",
}

LABEL_FONT_SIZE = 11

ITEM_CATEGORIES = [
    ("Pitched", "#bf55ec", {
        "black heart", "berserked", "total control", "commanding force earring",
        "cursed red spellbook", "dreamy belt", "endless terror", "genesis badge",
        "mitra rage", "magic eye patch", "source of suffering",
    }),
    ("Dawn", "#f0c040", {
        "daybreak", "slime ring",
    }),
    ("Brilliant", "#3498db", {
        "blissful nightmare", "whisper of the source", "oath of death", "immortal legacy",
        "original sin of pride",
    }),
    # Filled in from the user's own saved items — see BossTrackerApp._apply_custom_items.
    ("Custom", "#2ecc71", set()),
    ("Others", "#888888", set()),
]
CUSTOM_CATEGORY_NAMES = ITEM_CATEGORIES[-2][2]


def _hidden_from_shelf(name):
    """The Eternal gear pieces clutter the main page's Item Inventory — only the two
    Eternal Armor Boxes belong there. The files stay put, so every other screen that
    reads the assets folder still sees them."""
    n = name.lower()
    return n.startswith("eternal ") and "box" not in n

PITCHED_ITEMS = [
    ("Berserked", "Berserked.png"),
    ("Total Control", "Total Control.png"),
    ("Commanding Force Earring", "Commanding Force Earring.png"),
    ("Dreamy Belt", "Dreamy Belt.png"),
    ("Endless Terror", "Endless Terror.png"),
    ("Magic Eye Patch", "Magic Eye Patch.png"),
    ("Source Of Suffering", "Source Of Suffering.png"),
    ("Blissful Nightmare", "Blissful Nightmare.png"),
    ("Whisper of the Source", "Whisper of the Source.png"),
    ("Oath of Death", "Oath of Death.png"),
    ("DayBreak", "DayBreak.png"),
    ("Slime Ring", "Slime Ring.png"),
    ("Eternal Hat", "Eternal Hat.png"),
    ("Eternal Top", "Eternal Top.png"),
    ("Eternal Bottom", "Eternal Bottom.png"),
    ("Eternal Shoulder", "Eternal Shoulder.png"),
    ("Eternal Cape", "Eternal Cape.png"),
    ("Eternal Glove", "Eternal Glove.png"),
    ("Eternal Boots", "Eternal Boots.png"),
]

PITCHED_SOURCE_COUNT = 5
PITCHED_SOURCE_COLORS = ["#4fd1c5", "#e74c3c", "#9b59b6", "#8e44ad", "#f0c040"]
PITCHED_SOURCE_ICONS = ["Source 1.png", "Source 2.png", "Source 3.png", "Source 4.png", "Source 5.png"]
PITCHED_SOURCE_NAMES = ["Drops", "Trace Restoration", "Pitched Star Core", "Pitched Whispers", "Pitched Box"]

BOSS_DROPS = {
    ("lotus", "Hard"):              ["Black Heart", "Berserked"],
    ("lotus", "Extreme"):           ["Black Heart", "Berserked", "Total Control"],
    ("darknell", "Hard"):           ["Commanding Force Earring"],
    ("will", "Hard"):               ["Cursed Red Spellbook"],
    ("lucid", "Hard"):              ["Dreamy Belt"],
    ("gloom", "Chaos"):             ["Endless Terror"],
    ("blackmage", "Hard"):          ["Genesis Badge"],
    ("blackmage", "Extreme"):       ["Genesis Badge", "Exceptional Hammer (Belt)"],
    ("seren", "Normal"):            ["DayBreak"],
    ("seren", "Hard"):              ["DayBreak", "Mitra Rage"],
    ("seren", "Extreme"):           ["DayBreak", "Mitra Rage", "Exceptional Hammer (Face Acc)"],
    ("kalos", "Normal"):            ["Grindstone of Life"],
    ("kalos", "Chaos"):             ["Grindstone of Life", "Eternal Armor Box (Kalos)", "Life Boss Ring Box"],
    ("kalos", "Extreme"):           ["Grindstone of Life", "Exceptional Hammer (Eye Acc)", "Eternal Armor Box (Kalos)", "Life Boss Ring Box"],
    ("first adversary", "Normal"):  ["Grindstone of Life"],
    ("first adversary", "Hard"):    ["Grindstone of Life", "Immortal Legacy", "Eternal Armor Box (Kalos)", "Life Boss Ring Box"],
    ("first adversary", "Extreme"): ["Grindstone of Life", "Immortal Legacy", "Exceptional Hammer (Medal)", "Eternal Armor Box (Kalos)", "Life Boss Ring Box"],
    ("damien", "Hard"):             ["Magic Eye Patch"],
    ("baldrix", "Normal"):          ["Grindstone of Faith", "Life Boss Ring Box"],
    ("baldrix", "Hard"):            ["Grindstone of Faith", "Oath of Death", "Eternal Armor Box (Limbo)", "Life Boss Ring Box"],
    ("guardian angel slime", "Normal"): ["Slime Ring"],
    ("guardian angel slime", "Chaos"):  ["Slime Ring"],
    ("vhilla", "Normal"):           ["DayBreak"],
    ("vhilla", "Hard"):             ["DayBreak", "Source Of Suffering"],
    ("kaling", "Normal"):           ["Grindstone of Life"],
    ("kaling", "Hard"):             ["Grindstone of Faith", "Eternal Armor Box (Kalos)", "Life Boss Ring Box"],
    ("kaling", "Extreme"):          ["Grindstone of Faith", "Exceptional Hammer (Earrings)", "Eternal Armor Box (Kalos)", "Life Boss Ring Box"],
    ("limbo", "Normal"):            ["Grindstone of Faith", "Life Boss Ring Box"],
    ("limbo", "Hard"):              ["Grindstone of Faith", "Eternal Armor Box (Limbo)", "Life Boss Ring Box", "Whisper of the Source"],
    ("malefic star", "Normal"):     ["Grindstone of Life"],
    ("malefic star", "Hard"):       ["Grindstone of Faith", "Eternal Armor Box (Kalos)", "Life Boss Ring Box", "Blissful Nightmare"],
    ("jupiter", "Normal"):          ["Grindstone of Faith"],
    ("jupiter", "Hard"):            ["Grindstone of Faith", "Eternal Armor Box (Limbo)", "Life Boss Ring Box", "Original Sin of Pride"],
}

# Pristine copy of the built-in drop table. Custom items are merged on top of this each
# time they change, so removing one actually takes its drops back out.
_BUILTIN_BOSS_DROPS = {k: list(v) for k, v in BOSS_DROPS.items()}


def _item_state(item):
    if "state" in item:
        return item["state"]
    return 2 if item.get("checked", False) else 0


def _new_pitched_entry(name, icon_path=None):
    return {"name": name, "icon_path": icon_path, "sources": [0] * PITCHED_SOURCE_COUNT,
            "star": 0, "destructions": 0,
            "sessions": [{"star": 0, "entries": [], "destructions": 0}]}


def _default_difficulty(boss_name):
    tiers = list(BOSS_DIFFICULTY_MAP.get(boss_name, {"Normal": 0, "Hard": 0}).keys())
    for preferred in ("Hard", "Chaos"):
        if preferred in tiers:
            return preferred
    return tiers[-1]


LOWER_PRICE_THRESHOLD = 200_000_000


def _boss_worth(boss_name):
    """Highest crystal meso value across this boss's difficulty tiers."""
    tiers = BOSS_DIFFICULTY_MAP.get(boss_name)
    if not tiers:
        return 0
    return max(tiers.values())


def _fmt_meso_short(n):
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.2f}B"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    return f"{n:,}"


@functools.lru_cache(maxsize=None)
def _boss_files():
    """(full_path, lowercase_key, display_name) for every boss PNG, sorted by filename."""
    if not os.path.isdir(BOSS_ASSETS_DIR):
        return ()
    return tuple(
        (os.path.join(BOSS_ASSETS_DIR, f), os.path.splitext(f)[0].lower(), os.path.splitext(f)[0])
        for f in sorted(os.listdir(BOSS_ASSETS_DIR)) if f.lower().endswith('.png')
    )


@functools.lru_cache(maxsize=512)
def _scaled_pixmap(path, size):
    return QPixmap(path).scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation)


class DraggableAssetItem(QLabel):
    def __init__(self, name, image_path, show_price=False):
        super().__init__()
        self.name = name
        self.image_path = image_path

        self.setFixedSize(70, 80)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet("background-color: #2b2b2b; color: white; border-radius: 6px; border: 1px solid #3e3e3e;")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

        if show_price:
            tiers = BOSS_DIFFICULTY_MAP.get(name.lower())
            if tiers:
                self.setToolTip("\n".join(f"{diff}: {_fmt_meso_short(meso)}" for diff, meso in tiers.items()))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        self.img_label = QLabel()
        self.img_label.setPixmap(_scaled_pixmap(image_path, 32))
        self.img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.img_label)

        self.txt_label = QLabel(self.name)
        self.txt_label.setStyleSheet("font-size: 8px; font-weight: bold;")
        self.txt_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.txt_label.setWordWrap(True)
        layout.addWidget(self.txt_label)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            drag = QDrag(self)
            mime_data = QMimeData()
            mime_data.setText(f"{self.image_path}|{self.name}")
            drag.setMimeData(mime_data)
            drag.setPixmap(self.img_label.pixmap())
            drag.exec(Qt.DropAction.CopyAction)


class ClickableCellIcon(QWidget):
    def __init__(self, item_index, image_path, item_state, difficulty_text, party_size, is_inherited, left_click_cb,
                 right_click_cb, party_click_cb=None, boss_key=None, is_converted=False):
        super().__init__()
        self.item_index = item_index
        self.left_click_cb = left_click_cb
        self.right_click_cb = right_click_cb
        self.party_click_cb = party_click_cb

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(1)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.img_label = QLabel()
        self.img_label.setFixedSize(35, 35)
        self.img_label.setCursor(Qt.CursorShape.PointingHandCursor)

        base_pixmap = _scaled_pixmap(image_path, 35)

        item_stem = os.path.splitext(os.path.basename(image_path))[0].lower()
        overlay_name = SPECIAL_ITEM_OVERLAYS.get(item_stem)

        # FIXED: Translucent visual treatment for inherited scrolling timeline entries
        if is_inherited:
            inherited_pixmap = QPixmap(base_pixmap.size())
            inherited_pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(inherited_pixmap)
            painter.setOpacity(0.60)
            painter.drawPixmap(0, 0, base_pixmap)
            painter.end()
            self.img_label.setPixmap(inherited_pixmap)
            self.img_label.setToolTip(
                "Rolling Rollover Clear\nLeft-click icon: Modify difficulty here\nRight-click: Break chain")
        else:
            if item_state == 2:
                final_pixmap = QPixmap(base_pixmap.size())
                final_pixmap.fill(Qt.GlobalColor.transparent)
                painter = QPainter(final_pixmap)
                painter.setOpacity(0.4)
                painter.drawPixmap(0, 0, base_pixmap)
                painter.setOpacity(0.3)
                painter.setBrush(QColor(50, 50, 50))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawRect(0, 0, 35, 35)
                painter.end()
            elif item_state == 1:
                final_pixmap = QPixmap(base_pixmap.size())
                final_pixmap.fill(Qt.GlobalColor.transparent)
                painter = QPainter(final_pixmap)
                painter.setOpacity(0.85)
                painter.drawPixmap(0, 0, base_pixmap)
                painter.setOpacity(0.38)
                painter.setBrush(QColor(180, 55, 20))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawRect(0, 0, 35, 35)
                painter.end()
            else:
                final_pixmap = base_pixmap

            if is_converted and overlay_name:
                overlay_path = os.path.join(ITEMS_ASSETS_DIR, f"{overlay_name}.png")
                if os.path.exists(overlay_path):
                    final_pixmap = QPixmap(final_pixmap)
                    overlay_pixmap = _scaled_pixmap(overlay_path, 18)
                    painter = QPainter(final_pixmap)
                    painter.drawPixmap(35 - overlay_pixmap.width(), 35 - overlay_pixmap.height(), overlay_pixmap)
                    painter.end()

            self.img_label.setPixmap(final_pixmap)

            if difficulty_text is None:
                if boss_key:
                    bparts = boss_key.split("|", 1)
                    bname = bparts[0].replace("_", " ").title()
                    bdiff = bparts[1].title() if len(bparts) > 1 else ""
                    boss_line = f"\nFrom: {bname} ({bdiff})" if bdiff else f"\nFrom: {bname}"
                else:
                    boss_line = ""
                if overlay_name:
                    self.img_label.setToolTip(
                        f"Item Drop{boss_line}\nLeft-click: Toggle\n"
                        f"  Normal  = obtained & counted\n"
                        f"  With badge = converted into {overlay_name}\n"
                        "Right-click: Remove item")
                else:
                    self.img_label.setToolTip(
                        f"Item Drop{boss_line}\nLeft-click: Cycle state\n"
                        "  Normal  = obtained & counted\n"
                        "  Red tint = dropped, not collected (not counted)\n"
                        "  Grey    = ignored / won't count\n"
                        "Right-click: Remove item")
            else:
                self.img_label.setToolTip(
                    "Explicit Week Entry\nLeft-click icon: Cycle Difficulty\nRight-click: Delete configuration stamp")

        layout.addWidget(self.img_label)

        if difficulty_text:
            text_hbox = QHBoxLayout()
            text_hbox.setContentsMargins(0, 0, 0, 0)
            text_hbox.setSpacing(2)
            text_hbox.setAlignment(Qt.AlignmentFlag.AlignCenter)

            self.diff_label = QLabel(difficulty_text)
            fs = LABEL_FONT_SIZE
            if difficulty_text == "Extreme":
                self.diff_label.setStyleSheet(
                    f"font-size: {fs}px; color: #bf55ec; font-weight: bold; background: transparent;")
            elif difficulty_text == "Chaos":
                self.diff_label.setStyleSheet(
                    f"font-size: {fs}px; color: #ff9900; font-weight: bold; background: transparent;")
            elif difficulty_text == "Hard":
                self.diff_label.setStyleSheet(
                    f"font-size: {fs}px; color: #ff3333; font-weight: bold; background: transparent;")
            elif difficulty_text == "Easy":
                self.diff_label.setStyleSheet(
                    f"font-size: {fs}px; color: #2ecc71; font-weight: bold; background: transparent;")
            else:
                self.diff_label.setStyleSheet(
                    f"font-size: {fs}px; color: #a0a0a0; font-weight: bold; background: transparent;")
            self.diff_label.setCursor(Qt.CursorShape.PointingHandCursor)
            self.diff_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            text_hbox.addWidget(self.diff_label)

            self.party_label = QLabel(f"({party_size})")
            self.party_label.setStyleSheet(
                f"font-size: {fs}px; color: #3498db; font-weight: bold; background: transparent; padding-left: 1px;")
            self.party_label.setCursor(Qt.CursorShape.PointingHandCursor)
            self.party_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            text_hbox.addWidget(self.party_label)

            self.party_label.mousePressEvent = self.handle_party_label_click

            container_widget = QWidget()
            container_widget.setLayout(text_hbox)
            layout.addWidget(container_widget)

    def handle_party_label_click(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.party_click_cb is not None:
            self.party_click_cb(self.item_index)
            event.accept()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self.left_click_cb is not None:
                self.left_click_cb(self.item_index)
        elif event.button() == Qt.MouseButton.RightButton:
            if self.right_click_cb is not None:
                self.right_click_cb(self.item_index)
            event.accept()


class BlackMageToggle(QLabel):
    """Checkbox for the monthly Black Mage clear (no drag-and-drop)."""
    def __init__(self, image_path, is_done, difficulty_text, click_cb, right_click_cb):
        super().__init__()
        self.click_cb = click_cb
        self.remove_cb = right_click_cb
        self.setFixedSize(35, 35)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        base_pixmap = _scaled_pixmap(image_path, 35)
        if is_done:
            self.setPixmap(base_pixmap)
            self.setStyleSheet("border: 2px solid #2ecc71; border-radius: 4px;")
            self.setToolTip(f"Black Mage ({difficulty_text}) — Monthly\n"
                             "Left-click: Uncheck\nRight-click: Edit difficulty / party size")
        else:
            dim_pixmap = QPixmap(base_pixmap.size())
            dim_pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(dim_pixmap)
            painter.setOpacity(0.35)
            painter.drawPixmap(0, 0, base_pixmap)
            painter.end()
            self.setPixmap(dim_pixmap)
            self.setStyleSheet("border: 1px dashed #888888; border-radius: 4px;")
            self.setToolTip("Black Mage (Monthly)\nClick to mark done this month")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.click_cb()
        elif event.button() == Qt.MouseButton.RightButton:
            self.remove_cb()
        event.accept()


class DynamicCalendarCell(QFrame):
    def __init__(self, char_id, week_key, is_current_week, drop_cb, left_click_cb, right_click_cb,
                 party_click_cb=None, wrap_cols=None, min_size=None):
        super().__init__()
        self.char_id = char_id
        self.week_key = week_key
        self.is_current_week = is_current_week
        self.drop_cb = drop_cb
        self.left_click_cb = left_click_cb
        self.right_click_cb = right_click_cb
        self.party_click_cb = party_click_cb
        self.wrap_cols = wrap_cols
        self._icon_count = 0

        self.setFrameShape(QFrame.Shape.Box)
        self.default_style = "background-color: #221c16; border: 1px dashed #ff9900; border-radius: 4px;" if self.is_current_week else "background-color: #1c1c1c; border: 1px solid #2d2d2d; border-radius: 4px;"
        self.setStyleSheet(self.default_style)
        self.setAcceptDrops(True)

        if wrap_cols:
            mw, mh = min_size if min_size else (220, 280)
            self.setMinimumSize(mw, mh)
            self.main_layout = QGridLayout(self)
            self.main_layout.setContentsMargins(6, 6, 6, 6)
            self.main_layout.setSpacing(8)
            self.main_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        else:
            self.setMinimumSize(140, 95)
            self.main_layout = QHBoxLayout(self)
            self.main_layout.setContentsMargins(4, 4, 4, 4)
            self.main_layout.setSpacing(6)
            self.main_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

    def add_icon(self, index, image_path, item_state=0, difficulty_text=None, party_size=1, is_inherited=False, boss_key=None, is_converted=False):
        if image_path and os.path.exists(image_path):
            l_wrapper = lambda idx=index: self.left_click_cb(self.char_id, self.week_key, idx)
            r_wrapper = lambda idx=index: self.right_click_cb(self.char_id, self.week_key, idx)
            p_wrapper = (lambda idx=index: self.party_click_cb(self.char_id, self.week_key,
                                                               idx)) if self.party_click_cb else None

            icon_widget = ClickableCellIcon(index, image_path, item_state, difficulty_text, party_size, is_inherited,
                                            l_wrapper, r_wrapper, p_wrapper, boss_key=boss_key, is_converted=is_converted)
            if self.wrap_cols:
                row = self._icon_count // self.wrap_cols
                col = self._icon_count % self.wrap_cols
                self.main_layout.addWidget(icon_widget, row, col)
                self._icon_count += 1
            else:
                self.main_layout.addWidget(icon_widget)

    def add_custom_widget(self, widget):
        if self.wrap_cols:
            row = self._icon_count // self.wrap_cols
            col = self._icon_count % self.wrap_cols
            self.main_layout.addWidget(widget, row, col)
            self._icon_count += 1
        else:
            self.main_layout.addWidget(widget)

    def dragEnterEvent(self, event):
        if event.mimeData().hasText():
            event.acceptProposedAction()
            self.setStyleSheet("background-color: #2a2a2a; border: 2px solid #e67e22; border-radius: 4px;")

    def dragLeaveEvent(self, event):
        self.setStyleSheet(self.default_style)

    def dropEvent(self, event):
        data = event.mimeData().text()
        if "|" in data:
            image_path, _ = data.split("|")
            self.drop_cb(self.char_id, self.week_key, image_path)
            event.acceptProposedAction()
        self.setStyleSheet(self.default_style)


class BossHoverPreview(QWidget):
    def __init__(self):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("background-color: #1e1e1e; border: 1px solid #e67e22; border-radius: 6px;")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 8, 10, 10)
        outer.setSpacing(5)

        self._title = QLabel("")
        self._title.setStyleSheet("color: #e67e22; font-size: 13px; font-weight: bold; background: transparent; border: none;")
        outer.addWidget(self._title)

        self._sub = QLabel("")
        self._sub.setStyleSheet("color: #888888; font-size: 10px; background: transparent; border: none;")
        outer.addWidget(self._sub)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #333333; background-color: #333333; border: none;")
        sep.setFixedHeight(1)
        outer.addWidget(sep)

        self._grid_container = QWidget()
        self._grid_container.setStyleSheet("background: transparent; border: none;")
        self._grid = QGridLayout(self._grid_container)
        self._grid.setSpacing(8)
        outer.addWidget(self._grid_container)

    def populate(self, char_name, boss_entries, week_label, crystal_count=0, weekly_meso=0):
        self._title.setText(char_name)
        self._sub.setText(f"This Week  •  {week_label}")

        while self._grid.count():
            item = self._grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        diff_colors = {
            "Extreme": "#bf55ec", "Chaos": "#ff9900",
            "Hard": "#ff3333", "Easy": "#2ecc71", "Normal": "#a0a0a0",
        }

        if not boss_entries:
            lbl = QLabel("No bosses set for this week")
            lbl.setStyleSheet("color: #666666; font-size: 10px; background: transparent; border: none;")
            self._grid.addWidget(lbl, 0, 0)
        else:
            cols = 3
            for idx, (img_path, difficulty, party_size, is_inherited) in enumerate(boss_entries):
                r, c = divmod(idx, cols)
                cell = QWidget()
                cell.setStyleSheet("background: transparent; border: none;")
                cl = QVBoxLayout(cell)
                cl.setContentsMargins(2, 2, 2, 2)
                cl.setSpacing(2)
                cl.setAlignment(Qt.AlignmentFlag.AlignCenter)

                img_lbl = QLabel()
                img_lbl.setFixedSize(42, 42)
                pix = _scaled_pixmap(img_path, 42)
                if is_inherited:
                    faded = QPixmap(pix.size())
                    faded.fill(Qt.GlobalColor.transparent)
                    p = QPainter(faded)
                    p.setOpacity(0.55)
                    p.drawPixmap(0, 0, pix)
                    p.end()
                    img_lbl.setPixmap(faded)
                    img_lbl.setToolTip("Inherited from previous week")
                else:
                    img_lbl.setPixmap(pix)
                img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                img_lbl.setStyleSheet("background: transparent; border: none;")
                cl.addWidget(img_lbl)

                color = diff_colors.get(difficulty, "#a0a0a0")
                diff_lbl = QLabel(difficulty)
                diff_lbl.setStyleSheet(f"color: {color}; font-size: 9px; font-weight: bold; background: transparent; border: none;")
                diff_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                cl.addWidget(diff_lbl)

                if party_size > 1:
                    p_lbl = QLabel(f"({party_size}p)")
                    p_lbl.setStyleSheet("color: #777777; font-size: 8px; background: transparent; border: none;")
                    p_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    cl.addWidget(p_lbl)

                self._grid.addWidget(cell, r, c)

        # Separator + crystal/meso footer
        num_rows = (max(len(boss_entries), 1) + 2) // 3
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet("color: #333333; background-color: #333333; border: none;")
        sep2.setFixedHeight(1)
        self._grid.addWidget(sep2, num_rows, 0, 1, 3)

        crystal_color = "#2ecc71" if crystal_count <= 14 else "#ff3333"
        crystal_lbl = QLabel(f"Crystals: {crystal_count}/14")
        crystal_lbl.setStyleSheet(f"color: {crystal_color}; font-size: 10px; font-weight: bold; background: transparent; border: none;")
        crystal_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._grid.addWidget(crystal_lbl, num_rows + 1, 0, 1, 2)

        meso_lbl = QLabel(f"Meso: {_fmt_meso_short(weekly_meso)}")
        meso_lbl.setStyleSheet("color: #f0c040; font-size: 10px; font-weight: bold; background: transparent; border: none;")
        meso_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._grid.addWidget(meso_lbl, num_rows + 1, 2)

        self.adjustSize()


class CharacterProfileCard(QFrame):
    def __init__(self, char_data, click_callback, delete_callback, rename_callback,
                 move_up_callback=None, move_down_callback=None, hover_callback=None,
                 toggle_meso_cb=None, reorder_cb=None, is_completed=False, complete_cb=None,
                 task_summary=None, blackmage_done=False, blackmage_difficulty=None,
                 blackmage_click_cb=None, blackmage_edit_cb=None):
        super().__init__()
        self.char_id = char_data["id"]
        self.click_callback = click_callback
        self.hover_callback = hover_callback
        self.toggle_meso_cb = toggle_meso_cb
        self.reorder_cb = reorder_cb
        self._drag_start_pos = None

        is_excluded = char_data.get("meso_excluded", False)
        self._is_excluded = is_excluded

        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(self._normal_style())
        self.setFixedWidth(160)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Left-click / drag: open or reorder\nRight-click: toggle meso exclusion from statistics")
        self.setAcceptDrops(True)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        name_row = QHBoxLayout()
        name_row.setSpacing(6)
        name_row.setContentsMargins(0, 0, 0, 0)

        name_lbl = QLabel(char_data["name"])
        name_color = "#666666" if is_excluded else "#ffffff"
        name_lbl.setStyleSheet(
            f"font-weight: bold; color: {name_color}; font-size: 14px; background: transparent; border:none;")
        name_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        name_row.addWidget(name_lbl)

        if blackmage_click_cb is not None:
            if os.path.exists(_BM_PATH):
                bm_toggle = BlackMageToggle(_BM_PATH, blackmage_done, blackmage_difficulty,
                                            click_cb=blackmage_click_cb,
                                            right_click_cb=blackmage_edit_cb or (lambda: None))
                name_row.addWidget(bm_toggle)

        name_row.addStretch()
        layout.addLayout(name_row)

        if task_summary:
            task_lbl = QLabel(task_summary)
            task_lbl.setStyleSheet("color: #888888; font-size: 10px; background: transparent; border: none;")
            task_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            layout.addWidget(task_lbl)

        if is_excluded:
            excl_lbl = QLabel("meso excluded")
            excl_lbl.setStyleSheet("color: #444444; font-size: 10px; background: transparent; border:none;")
            excl_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            layout.addWidget(excl_lbl)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)

        btn_rename = QPushButton("Rename")
        btn_rename.setStyleSheet(
            "QPushButton { background-color: #1a3a5a; color: #66aaff; border-radius: 3px; padding: 2px 6px; font-size: 11px; border: none; }"
            "QPushButton:hover { background-color: #1f5080; color: white; }")
        btn_rename.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_rename.clicked.connect(lambda: rename_callback(self.char_id, char_data["name"]))
        btn_row.addWidget(btn_rename)

        btn_delete = QPushButton("Delete")
        btn_delete.setStyleSheet(
            "QPushButton { background-color: #5a1a1a; color: #ff6666; border-radius: 3px; padding: 2px 6px; font-size: 11px; border: none; }"
            "QPushButton:hover { background-color: #7b2222; color: white; }")
        btn_delete.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_delete.clicked.connect(lambda: delete_callback(self.char_id, char_data["name"]))
        btn_row.addWidget(btn_delete)

        layout.addLayout(btn_row)

        order_row = QHBoxLayout()
        order_row.setSpacing(4)

        btn_up = QPushButton("▲")
        btn_up.setStyleSheet(
            "QPushButton { background-color: #2a2a4a; color: #8888ff; border-radius: 3px; padding: 2px 8px; font-size: 11px; border: none; }"
            "QPushButton:hover { background-color: #3a3a6a; color: white; }")
        btn_up.setCursor(Qt.CursorShape.PointingHandCursor)
        if move_up_callback:
            btn_up.clicked.connect(lambda: move_up_callback(self.char_id))
        order_row.addWidget(btn_up)

        btn_down = QPushButton("▼")
        btn_down.setStyleSheet(
            "QPushButton { background-color: #2a2a4a; color: #8888ff; border-radius: 3px; padding: 2px 8px; font-size: 11px; border: none; }"
            "QPushButton:hover { background-color: #3a3a6a; color: white; }")
        btn_down.setCursor(Qt.CursorShape.PointingHandCursor)
        if move_down_callback:
            btn_down.clicked.connect(lambda: move_down_callback(self.char_id))
        order_row.addWidget(btn_down)

        layout.addLayout(order_row)

        done_row = QHBoxLayout()
        done_row.setSpacing(4)
        btn_done = QPushButton("✓ Done" if is_completed else "Mark Done")
        if is_completed:
            btn_done.setStyleSheet(
                "QPushButton { background-color: #1a5c1a; color: #2ecc71; border-radius: 3px; padding: 3px 6px;"
                " font-size: 11px; font-weight: bold; border: 1px solid #2ecc71; }"
                "QPushButton:hover { background-color: #1e7a1e; color: white; }")
        else:
            btn_done.setStyleSheet(
                "QPushButton { background-color: #2a2a2a; color: #666666; border-radius: 3px; padding: 3px 6px;"
                " font-size: 11px; border: 1px solid #3a3a3a; }"
                "QPushButton:hover { background-color: #333333; color: #aaaaaa; }")
        btn_done.setCursor(Qt.CursorShape.PointingHandCursor)
        if complete_cb:
            btn_done.clicked.connect(lambda: complete_cb(self.char_id))
        done_row.addWidget(btn_done)
        layout.addLayout(done_row)

    def _normal_style(self):
        if self._is_excluded:
            return ("QFrame { background-color: #111111; padding: 6px; border-radius: 4px; border: 1px solid #1e1e1e; }"
                    " QFrame:hover { background-color: #1a1a1a; border: 1px solid #666666; }")
        return ("QFrame { background-color: #1a1a1a; padding: 6px; border-radius: 4px; border: 1px solid #252525; }"
                " QFrame:hover { background-color: #252525; border: 1px solid #e67e22; }")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = event.pos()
        elif event.button() == Qt.MouseButton.RightButton:
            if self.toggle_meso_cb:
                self.toggle_meso_cb(self.char_id)

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.MouseButton.LeftButton) or self._drag_start_pos is None:
            return
        if (event.pos() - self._drag_start_pos).manhattanLength() < QApplication.startDragDistance():
            return
        self._drag_start_pos = None
        drag = QDrag(self)
        mime = QMimeData()
        mime.setText(f"char_drag:{self.char_id}")
        drag.setMimeData(mime)
        pix = self.grab()
        drag.setPixmap(pix)
        drag.setHotSpot(event.pos())
        drag.exec(Qt.DropAction.MoveAction)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._drag_start_pos is not None:
            self._drag_start_pos = None
            self.click_callback(self.char_id)

    def dragEnterEvent(self, event):
        if event.mimeData().hasText() and event.mimeData().text().startswith("char_drag:"):
            dragged_id = int(event.mimeData().text().split(":")[1])
            if dragged_id != self.char_id:
                event.acceptProposedAction()
                self.setStyleSheet(
                    "QFrame { background-color: #1a2a3a; padding: 6px; border-radius: 4px; border: 2px solid #2980b9; }")

    def dragLeaveEvent(self, event):
        self.setStyleSheet(self._normal_style())

    def dropEvent(self, event):
        self.setStyleSheet(self._normal_style())
        if event.mimeData().hasText() and event.mimeData().text().startswith("char_drag:"):
            dragged_id = int(event.mimeData().text().split(":")[1])
            if dragged_id != self.char_id and self.reorder_cb:
                self.reorder_cb(dragged_id, self.char_id)
            event.acceptProposedAction()

    def enterEvent(self, event):
        if self.hover_callback:
            self.hover_callback(self.char_id, True, self)
        super().enterEvent(event)

    def leaveEvent(self, event):
        if self.hover_callback:
            self.hover_callback(self.char_id, False, None)
        super().leaveEvent(event)


class MesoBarChart(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._data = []
        self.setMinimumHeight(120)

    def set_data(self, data):
        self._data = data
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#1a1a1a"))

        if not self._data or all(v == 0 for _, v in self._data):
            painter.setPen(QColor("#555555"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No data")
            painter.end()
            return

        W, H = self.width(), self.height()
        ml, mr, mt, mb = 8, 8, 22, 28
        cw = W - ml - mr
        ch = H - mt - mb
        n = len(self._data)
        max_val = max(v for _, v in self._data) or 1

        slot_w = cw / n
        bar_w = slot_w * 0.55
        f_val = QFont("Segoe UI", 7)
        f_val.setBold(True)
        f_lbl = QFont("Segoe UI", 8)

        for i, (label, val) in enumerate(self._data):
            x = ml + i * slot_w + (slot_w - bar_w) / 2
            bh = (val / max_val) * ch
            y = mt + ch - bh

            grad = QLinearGradient(x, y, x, y + bh)
            grad.setColorAt(0, QColor("#f0c040"))
            grad.setColorAt(1, QColor("#c0782a"))
            painter.setBrush(grad)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(int(x), int(y), int(bar_w), int(bh) + 1, 3, 3)

            painter.setFont(f_val)
            painter.setPen(QColor("#f0c040"))
            painter.drawText(int(x - 4), int(y) - 16, int(bar_w + 8), 16,
                             Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom, self._fmt(val))

            painter.setFont(f_lbl)
            painter.setPen(QColor("#b3b3b3"))
            painter.drawText(int(x - 4), mt + ch + 4, int(bar_w + 8), mb - 4,
                             Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, label)

        painter.end()

    @staticmethod
    def _fmt(n):
        if n >= 1_000_000_000:
            return f"{n / 1_000_000_000:.1f}B"
        if n >= 1_000_000:
            return f"{n / 1_000_000:.0f}M"
        return f"{n:,}"


class _NumItem(QTableWidgetItem):
    """QTableWidgetItem that sorts numerically instead of lexicographically."""
    def __init__(self, num_val, display=""):
        super().__init__(display if display else str(num_val))
        self._num = num_val

    def __lt__(self, other):
        if isinstance(other, _NumItem):
            return self._num < other._num
        return super().__lt__(other)


# --- Item Scanner: Windows built-in OCR (Windows.Media.Ocr via PowerShell/WinRT), no extra install needed ---
_OCR_POWERSHELL_SCRIPT = r'''
param([string]$ImagePath)
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($WinRtTask, $ResultType) {
    $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
    $netTask = $asTask.Invoke($null, @($WinRtTask))
    $netTask.Wait(-1) | Out-Null
    $netTask.Result
}
[Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
[Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics, ContentType = WindowsRuntime] | Out-Null
$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($ImagePath)) ([Windows.Storage.StorageFile])
$stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if ($null -eq $engine) { Write-Output "__OCR_ENGINE_UNAVAILABLE__"; exit }
$result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
Write-Output $result.Text
'''

# --- Global hotkey (F9) so capture can fire while hovering an item, without moving the mouse ---
_WM_HOTKEY = 0x0312
_WM_QUIT = 0x0012
_MOD_NOREPEAT = 0x4000
_VK_F9 = 0x78
_SCAN_HOTKEY_ID = 1


class _GlobalHotkeyListener(QThread):
    """Registers a system-wide hotkey (default F9) and emits `triggered` on every press.

    Runs its own Win32 message loop on this thread (RegisterHotKey requires a message
    pump on the registering thread) and posts WM_QUIT to itself in stop() to exit cleanly.
    """
    triggered = pyqtSignal()

    def __init__(self, modifiers=_MOD_NOREPEAT, vk=_VK_F9):
        super().__init__()
        self._modifiers = modifiers
        self._vk = vk
        self._thread_id = None
        self._registered = False

    def run(self):
        user32 = ctypes.windll.user32
        self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        self._registered = bool(user32.RegisterHotKey(None, _SCAN_HOTKEY_ID, self._modifiers, self._vk))
        if not self._registered:
            return
        msg = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
                if msg.message == _WM_HOTKEY and msg.wParam == _SCAN_HOTKEY_ID:
                    self.triggered.emit()
        finally:
            user32.UnregisterHotKey(None, _SCAN_HOTKEY_ID)

    def stop(self):
        if self._thread_id:
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, _WM_QUIT, 0, 0)
        self.wait(1000)


def _get_cursor_pos():
    pt = wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def _pixmap_to_rgb_array(pixmap: QPixmap) -> np.ndarray:
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    pixmap.save(buffer, "PNG")
    png_bytes = bytes(buffer.data())
    buffer.close()
    img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    return np.array(img)


def _find_robust_seed(brightness: np.ndarray, cx: int, cy: int, dark_thr: int = 110,
                       patch: int = 5, patch_min_mean: float = 0.7, max_radius: int = 60):
    """Spiral outward from (cx, cy) for a pixel that's dark AND sits in a locally-dark
    neighborhood — avoids latching onto a stray noisy/anti-aliased pixel right at an icon edge."""
    h, w = brightness.shape
    r_ = patch // 2

    def patch_ok(x, y):
        y0, y1 = max(0, y - r_), min(h, y + r_ + 1)
        x0, x1 = max(0, x - r_), min(w, x + r_ + 1)
        local = brightness[y0:y1, x0:x1]
        return (local <= dark_thr).mean() >= patch_min_mean

    if 0 <= cy < h and 0 <= cx < w and brightness[cy, cx] <= dark_thr and patch_ok(cx, cy):
        return cx, cy
    for r in range(1, max_radius):
        candidates = [(cx + dx, cy + dy) for dx in range(-r, r + 1) for dy in (-r, r)]
        candidates += [(cx + dx, cy + dy) for dy in range(-r + 1, r) for dx in (-r, r)]
        for x, y in candidates:
            if 0 <= y < h and 0 <= x < w and brightness[y, x] <= dark_thr and patch_ok(x, y):
                return x, y
    return None


def _grow_dark_rect(brightness: np.ndarray, seed_x: int, seed_y: int, mean_thr: int = 115, max_iter: int = 3000):
    """Grow a rectangle from a seed pixel while each new edge's MEAN brightness stays below
    mean_thr — robust to per-pixel JPEG/compression noise, unlike a hard per-pixel threshold."""
    h, w = brightness.shape
    left = right = seed_x
    top = bottom = seed_y
    changed = True
    it = 0
    while changed and it < max_iter:
        changed = False
        it += 1
        if left > 0:
            col = brightness[top:bottom + 1, left - 1]
            if col.size and col.mean() <= mean_thr:
                left -= 1
                changed = True
        if right < w - 1:
            col = brightness[top:bottom + 1, right + 1]
            if col.size and col.mean() <= mean_thr:
                right += 1
                changed = True
        if top > 0:
            row = brightness[top - 1, left:right + 1]
            if row.size and row.mean() <= mean_thr:
                top -= 1
                changed = True
        if bottom < h - 1:
            row = brightness[bottom + 1, left:right + 1]
            if row.size and row.mean() <= mean_thr:
                bottom += 1
                changed = True
    return left, top, right, bottom


def _detect_tooltip_region(full_pixmap: QPixmap, cursor_x: int, cursor_y: int):
    """Best-effort auto-crop of a game tooltip near the cursor. Returns a QRect in full-screen
    coordinates, or None if nothing confident was found (caller should fall back to manual select).

    Heuristic, not exact — tuned and validated against a sample tooltip, but can still return a
    wrong-but-"confident" crop on unusual layouts (e.g. a lighter seam splitting the tooltip in
    two blocks growth). Always show the thumbnail so the user can catch a bad auto-crop."""
    win_half_w, win_half_h = 480, 480
    x0 = max(0, cursor_x - win_half_w)
    y0 = max(0, cursor_y - win_half_h)
    x1 = min(full_pixmap.width(), cursor_x + win_half_w)
    y1 = min(full_pixmap.height(), cursor_y + win_half_h)
    if x1 - x0 < 20 or y1 - y0 < 20:
        return None

    crop = full_pixmap.copy(QRect(x0, y0, x1 - x0, y1 - y0))
    arr = _pixmap_to_rgb_array(crop)
    brightness = arr.max(axis=2).astype(np.int16)
    local_cx, local_cy = cursor_x - x0, cursor_y - y0

    seed = _find_robust_seed(brightness, local_cx, local_cy)
    if seed is None:
        return None
    seed_x, seed_y = seed
    left, top, right, bottom = _grow_dark_rect(brightness, seed_x, seed_y)
    width, height = right - left + 1, bottom - top + 1
    crop_w, crop_h = arr.shape[1], arr.shape[0]

    if width < 100 or height < 100:
        return None
    if width > 0.9 * crop_w or height > 0.9 * crop_h:
        return None

    pad = 3
    final_left = max(0, x0 + left - pad)
    final_top = max(0, y0 + top - pad)
    final_right = min(full_pixmap.width(), x0 + right + pad)
    final_bottom = min(full_pixmap.height(), y0 + bottom + pad)
    return QRect(final_left, final_top, final_right - final_left, final_bottom - final_top)


def _count_star_icons(pixmap: QPixmap, band_frac: float = 0.10, min_area: int = 8):
    """Count filled (gold) star icons in the top band of a MapleStory item tooltip — Star Force
    level is shown as a grid of star icons there (gold = filled, dark outline = empty), not as a
    printed number, so this can't be read by OCR at all. Validated against two real tooltips
    (both counted correctly) via gold-color blob counting rather than text recognition.

    Returns None if no confident gold blobs of consistent size are found."""
    arr = _pixmap_to_rgb_array(pixmap)
    h, w = arr.shape[:2]
    band_h = max(1, int(h * band_frac))
    band = arr[:band_h, :, :].astype(np.int16)
    r, g, b = band[:, :, 0], band[:, :, 1], band[:, :, 2]
    mask = (r > 140) & (g > 110) & (b < r - 50) & (b < g - 30)
    if not mask.any():
        return None

    visited = np.zeros_like(mask, dtype=bool)
    bh, bw = mask.shape
    count = 0
    for y in range(bh):
        for x in range(bw):
            if mask[y, x] and not visited[y, x]:
                stack = [(y, x)]
                visited[y, x] = True
                area = 0
                while stack:
                    cy, cx = stack.pop()
                    area += 1
                    for dy in (-1, 0, 1):
                        for dx in (-1, 0, 1):
                            ny, nx = cy + dy, cx + dx
                            if 0 <= ny < bh and 0 <= nx < bw and mask[ny, nx] and not visited[ny, nx]:
                                visited[ny, nx] = True
                                stack.append((ny, nx))
                if area >= min_area:
                    count += 1
    return count if count > 0 else None


class _RegionCaptureOverlay(QWidget):
    """Full-screen frozen-screenshot overlay for drag-selecting a capture region."""

    def __init__(self, screenshot: QPixmap, on_selected, on_cancel):
        super().__init__()
        self._pixmap = screenshot
        self._on_selected = on_selected
        self._on_cancel = on_cancel
        self._origin = None
        self._current_rect = QRect()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setGeometry(0, 0, screenshot.width(), screenshot.height())
        self.setCursor(Qt.CursorShape.CrossCursor)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self._pixmap)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 110))
        if not self._current_rect.isNull():
            painter.drawPixmap(self._current_rect, self._pixmap, self._current_rect)
            painter.setPen(QColor("#e67e22"))
            painter.drawRect(self._current_rect.adjusted(0, 0, -1, -1))

    def mousePressEvent(self, e):
        self._origin = e.position().toPoint()
        self._current_rect = QRect(self._origin, QSize())
        self.update()

    def mouseMoveEvent(self, e):
        if self._origin is not None:
            self._current_rect = QRect(self._origin, e.position().toPoint()).normalized()
            self.update()

    def mouseReleaseEvent(self, e):
        if self._origin is None:
            return
        rect = self._current_rect
        self.close()
        if rect.width() > 5 and rect.height() > 5:
            self._on_selected(self._pixmap.copy(rect))
        else:
            self._on_cancel()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.close()
            self._on_cancel()


class BossTrackerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MapleStory Weekly Boss Drop Tracker")
        self.setGeometry(50, 50, 1400, 850)
        self.setStyleSheet("background-color: #121212; color: #e0e0e0; font-family: Segoe UI, Arial, sans-serif;")
        self.setWindowIcon(QIcon(os.path.join(ITEMS_ASSETS_DIR, "Genesis Badge.png")))

        self.characters = []
        self.char_id_counter = 0
        self.saved_item_drops = {}
        self.saved_boss_clears = {}
        self.boss_presets = []
        self.custom_items = []
        self.items_shelf_layout = None
        self.selected_char_id = None
        self._resolve_cache = {}
        self._stats_dirty = True
        self.char_completed_weeks = set()
        self.char_tasks = {}
        self.global_tasks = []
        self.char_item_results = {}
        self.char_pitched_tracker = {}
        self.pitched_tracked_chars = []
        self._pitched_expanded = set()
        self._pitched_log_expanded = set()
        self.char_exclusion_history = {}
        self._all_tasks_update_in_progress = False
        self._task_drag_state = None
        self.tasks_sort_mode = "manual"
        self.item_results_sort_mode = "manual"

        today = datetime.now().date()
        offset = (today.weekday() - 3) % 7
        self.actual_current_thursday = today - timedelta(days=offset)
        self.actual_current_week_key = self.actual_current_thursday.strftime("%Y-%m-%d")

        self.base_thursday = self.actual_current_thursday
        self.view_week_offset = 0

        self.view_stack = QStackedWidget()
        self._boss_hover_preview = BossHoverPreview()
        self._pending_hover = None
        self._hover_timer = QTimer()
        self._hover_timer.setSingleShot(True)
        self._hover_timer.setInterval(250)
        self._hover_timer.timeout.connect(self._fire_hover_preview)

        self.setup_global_tab_bar()
        self.build_overview_page()
        self.build_boss_schedule_page()
        self.build_statistics_dashboard_page()
        self.build_version_history_page()
        self.build_all_tasks_page()
        self.build_item_results_page()
        self.build_pitched_items_page()
        if ENABLE_ITEM_SCANNER:
            self.build_item_scanner_page()

        self.view_stack.setCurrentIndex(0)
        self.load_data()
        self._font_size_display.setText(str(LABEL_FONT_SIZE))
        if getattr(self, '_loaded_last_seen_week', '') != self.actual_current_week_key:
            self._auto_populate_new_week()
        self.update_overview_calendar()

        if ENABLE_ITEM_SCANNER:
            self._scan_hotkey_listener = _GlobalHotkeyListener()
            self._scan_hotkey_listener.triggered.connect(self._start_item_scan)
            self._scan_hotkey_listener.start()

    def closeEvent(self, event):
        listener = getattr(self, '_scan_hotkey_listener', None)
        if listener is not None:
            listener.stop()
        super().closeEvent(event)

    def _active_bosses(self, cid, wkey, include_monthly=False):
        """[(path, key, display_name, state, inherited)] for every boss live on this week."""
        out = []
        for path, key, raw in _boss_files():
            if not include_monthly and key in MONTHLY_BOSSES:
                continue
            state, inherited = self.resolve_boss_state_at_week(cid, wkey, path)
            if state and not state.get("is_deleted_marker", False):
                out.append((path, key, raw, state, inherited))
        return out

    def get_current_week_bosses(self, char_id):
        return [(p, s["difficulty"], s.get("party_size", 1), inh)
                for p, _k, _r, s, inh in self._active_bosses(char_id, self.actual_current_week_key, include_monthly=True)]

    def _fire_hover_preview(self):
        char_id, card_widget = self._pending_hover
        char = next((c for c in self.characters if c["id"] == char_id), None)
        if char is None:
            return
        bosses = self.get_current_week_bosses(char_id)
        week_label = datetime.strptime(self.actual_current_week_key, "%Y-%m-%d").strftime("%b %d, %Y")
        crystal_count = sum(
            1 for path, diff, ps, inh in bosses
            if os.path.splitext(os.path.basename(path))[0].lower() not in MONTHLY_BOSSES
        )
        weekly_meso = self.calculate_weekly_crystal_meso(char_id, self.actual_current_week_key, ignore_completion=True)
        self._boss_hover_preview.populate(char["name"], bosses, week_label, crystal_count, weekly_meso)
        global_pos = card_widget.mapToGlobal(QPoint(card_widget.width() + 8, 0))
        self._boss_hover_preview.move(global_pos)
        self._boss_hover_preview.show()
        self._boss_hover_preview.raise_()

    def show_boss_hover_preview(self, char_id, show, card_widget):
        self._hover_timer.stop()
        if not show:
            self._boss_hover_preview.hide()
            return
        self._pending_hover = (char_id, card_widget)
        self._hover_timer.start()

    def save_data(self):
        data = {
            "characters": self.characters,
            "char_id_counter": self.char_id_counter,
            "boss_presets": self.boss_presets,
            "custom_items": self.custom_items,
            "last_seen_week": self.actual_current_week_key,
            "label_font_size": LABEL_FONT_SIZE,
            "char_completed_weeks": list(self.char_completed_weeks),
            "char_tasks": {str(k): v for k, v in self.char_tasks.items()},
            "global_tasks": self.global_tasks,
            "char_item_results": {str(k): v for k, v in self.char_item_results.items()},
            "char_pitched_tracker": {str(k): v for k, v in self.char_pitched_tracker.items()},
            "pitched_tracked_chars": self.pitched_tracked_chars,
            "char_exclusion_history": {str(k): v for k, v in self.char_exclusion_history.items()},
            "saved_item_drops": {
                f"{k[0]}|{k[1]}": v for k, v in self.saved_item_drops.items()
            },
            "saved_boss_clears": {
                f"{k[0]}|{k[1]}": v for k, v in self.saved_boss_clears.items()
            },
        }
        tmp = DATA_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, DATA_FILE)
        self._resolve_cache.clear()
        self._stats_dirty = True

    def load_data(self):
        if not os.path.exists(DATA_FILE):
            return
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.characters = data.get("characters", [])
            self.char_id_counter = data.get("char_id_counter", 0)
            self.boss_presets = data.get("boss_presets", [])
            self.custom_items = data.get("custom_items", [])
            self.saved_item_drops = {
                (int(k.split("|")[0]), k.split("|")[1]): v
                for k, v in data.get("saved_item_drops", {}).items()
            }
            self.saved_boss_clears = {
                (int(k.split("|")[0]), k.split("|")[1]): v
                for k, v in data.get("saved_boss_clears", {}).items()
            }
            self._loaded_last_seen_week = data.get("last_seen_week", "")
            self.char_completed_weeks = set(data.get("char_completed_weeks", []))
            self.char_tasks = {int(k): v for k, v in data.get("char_tasks", {}).items()}
            self.global_tasks = data.get("global_tasks", [])
            self.char_item_results = {int(k): v for k, v in data.get("char_item_results", {}).items()}
            self.char_pitched_tracker = {int(k): v for k, v in data.get("char_pitched_tracker", {}).items()}
            for cid, val in list(self.char_pitched_tracker.items()):
                if isinstance(val, dict):
                    # Legacy format: a dict pre-populated with all known items keyed by stem.
                    # Migrate to the opt-in list format, dropping untouched (all-zero) entries.
                    known_by_stem = {name.lower(): (name, fname) for name, fname in PITCHED_ITEMS}
                    migrated = []
                    for stem, entry in val.items():
                        sources = entry.get("sources", [0] * PITCHED_SOURCE_COUNT)
                        star = entry.get("star", 0)
                        destructions = entry.get("destructions", 0)
                        if not (any(sources) or star or destructions):
                            continue
                        display_name, fname = known_by_stem.get(stem, (stem.title(), None))
                        icon_path = os.path.join(ITEMS_ASSETS_DIR, fname) if fname else None
                        migrated.append({"name": display_name, "icon_path": icon_path,
                                          "sources": sources, "star": star, "destructions": destructions})
                    self.char_pitched_tracker[cid] = migrated
            if "pitched_tracked_chars" in data:
                self.pitched_tracked_chars = [int(c) for c in data.get("pitched_tracked_chars", [])]
            else:
                # First load under the opt-in system: keep whoever already had real data tracked.
                self.pitched_tracked_chars = [cid for cid, items in self.char_pitched_tracker.items() if items]
            self.char_exclusion_history = {int(k): v for k, v in data.get("char_exclusion_history", {}).items()}
            global LABEL_FONT_SIZE
            LABEL_FONT_SIZE = data.get("label_font_size", 11)
            self._backfill_missing_dates()
        except Exception as e:
            backup = DATA_FILE + ".corrupt"
            try:
                os.replace(DATA_FILE, backup)
            except OSError:
                pass
            QMessageBox.critical(
                self, "Data file unreadable",
                f"Could not read {os.path.basename(DATA_FILE)}:\n{e}\n\n"
                f"It was moved to {os.path.basename(backup)} so it won't be overwritten. Starting empty.")

    def _backfill_missing_dates(self):
        today = self._today_str()
        for entries in list(self.char_tasks.values()) + [self.global_tasks]:
            for entry in entries:
                if not entry.get("opened"):
                    entry["opened"] = today
                if entry.get("done") and not entry.get("closed"):
                    entry["closed"] = today
                elif "closed" not in entry:
                    entry["closed"] = None
        for cid, entries in list(self.char_item_results.items()):
            migrated = []
            for entry in entries:
                if "upgrades" not in entry:
                    # Legacy flat schema (item/upgrade_type/amount/result/done at top level) -> grouped schema
                    opened = entry.get("opened") or today
                    done = entry.get("done", False)
                    closed = entry.get("closed") or (today if done else None)
                    entry = {
                        "item": entry.get("item", ""),
                        "opened": opened,
                        "upgrades": [{
                            "upgrade_type": entry.get("upgrade_type", ""),
                            "amount": entry.get("amount", 0),
                            "result": entry.get("result", ""),
                            "target": entry.get("target", ""),
                            "done": done,
                            "opened": opened,
                            "closed": closed,
                        }],
                    }
                else:
                    if not entry.get("opened"):
                        entry["opened"] = today
                    for u in entry.get("upgrades", []):
                        if not u.get("opened"):
                            u["opened"] = today
                        if u.get("done") and not u.get("closed"):
                            u["closed"] = today
                        elif "closed" not in u:
                            u["closed"] = None
                        if "target" not in u:
                            u["target"] = ""
                migrated.append(entry)
            self.char_item_results[cid] = migrated
        self._apply_custom_items()
        self.save_data()

    def _populate_items_shelf(self):
        """(Re)fill the main page's Item Inventory from the assets folder, grouped by category."""
        while self.items_shelf_layout.count():
            w = self.items_shelf_layout.takeAt(0).widget()
            if w:
                w.deleteLater()
        if not os.path.exists(ITEMS_ASSETS_DIR):
            return

        all_items = [
            (os.path.splitext(f)[0], f)
            for f in sorted(os.listdir(ITEMS_ASSETS_DIR))
            if f.lower().endswith('.png') and not _hidden_from_shelf(os.path.splitext(f)[0])
        ]
        buckets = {cat: [] for cat, _, _ in ITEM_CATEGORIES}
        for name, file in all_items:
            name_lower = name.lower()
            placed = False
            for cat, _, names in ITEM_CATEGORIES[:-1]:
                if name_lower in names:
                    buckets[cat].append((name, file))
                    placed = True
                    break
            if not placed:
                buckets["Others"].append((name, file))

        row_idx = 0
        for cat, color, _ in ITEM_CATEGORIES:
            items = buckets[cat]
            if not items:
                continue
            sep = QLabel(cat)
            sep.setStyleSheet(
                f"color: {color}; font-size: 11px; font-weight: bold;"
                " padding: 4px 2px 2px 4px; background: transparent;")
            self.items_shelf_layout.addWidget(sep, row_idx, 0, 1, 3)
            row_idx += 1
            col_idx = 0
            for name, file in items:
                item_widget = DraggableAssetItem(name, os.path.join(ITEMS_ASSETS_DIR, file))
                self.items_shelf_layout.addWidget(item_widget, row_idx, col_idx)
                col_idx += 1
                if col_idx >= 3:
                    col_idx = 0
                    row_idx += 1
            if col_idx != 0:
                row_idx += 1

    # ==========================================
    # USER-DEFINED ITEMS
    # ==========================================
    def _apply_custom_items(self):
        """Fold the user's own items into the built-in drop table, then refresh the shelf.

        Everything downstream (drop-rate stats, the boss totals table, and the "which boss
        did this come from?" picker) reads BOSS_DROPS, so merging here is all that's needed
        to make custom items behave like built-in ones. A custom item is tied to whole
        bosses rather than single difficulties, so it is registered on every tier."""
        BOSS_DROPS.clear()
        BOSS_DROPS.update({k: list(v) for k, v in _BUILTIN_BOSS_DROPS.items()})
        CUSTOM_CATEGORY_NAMES.clear()

        for item in self.custom_items:
            CUSTOM_CATEGORY_NAMES.add(item["name"].lower())
            for boss_key in item.get("bosses", []):
                for diff in BOSS_DIFFICULTY_MAP.get(boss_key, {"Normal": 0}):
                    drops = BOSS_DROPS.setdefault((boss_key, diff), [])
                    if item["name"] not in drops:
                        drops.append(item["name"])

        self._resolve_cache.clear()
        self._stats_dirty = True
        if self.items_shelf_layout is not None:
            self._populate_items_shelf()

    def _custom_item_path(self, item):
        return os.path.join(ITEMS_ASSETS_DIR, item["file"])

    def add_custom_item_dialog(self):
        """Name + image + the bosses that drop it. Also lists existing custom items so a
        mistake can be taken back out without hand-editing the save file."""
        dialog = QDialog(self)
        dialog.setWindowTitle("Custom Items")
        dialog.setMinimumWidth(460)
        dialog.setStyleSheet("background-color: #1c1c1c; color: #e0e0e0;")
        outer = QVBoxLayout(dialog)

        form = QHBoxLayout()
        preview = QLabel("no\nimage")
        preview.setFixedSize(64, 64)
        preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview.setStyleSheet("border: 1px dashed #444; color: #666; font-size: 10px; border-radius: 4px;")
        form.addWidget(preview)

        right = QVBoxLayout()
        name_edit = QLineEdit()
        name_edit.setPlaceholderText("Item name")
        name_edit.setStyleSheet("background-color: #232323; border: 1px solid #333; border-radius: 3px; padding: 5px;")
        right.addWidget(name_edit)

        chosen = {"path": None}

        def pick_image():
            path, _ = QFileDialog.getOpenFileName(
                dialog, "Choose Item Image", "", "Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp)")
            if path:
                chosen["path"] = path
                preview.setPixmap(QPixmap(path).scaled(
                    60, 60, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

        btn_img = QPushButton("Choose Image…")
        btn_img.setStyleSheet(
            "QPushButton { background-color: #2a3a4a; color: #88bbff; border-radius: 3px; padding: 5px; border: none; }"
            "QPushButton:hover { background-color: #33506e; color: white; }")
        btn_img.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_img.clicked.connect(pick_image)
        right.addWidget(btn_img)
        form.addLayout(right)
        outer.addLayout(form)

        lbl = QLabel("Dropped by (tick every boss that drops it):")
        lbl.setStyleSheet("color: #e67e22; font-size: 12px; font-weight: bold; padding-top: 6px;")
        outer.addWidget(lbl)

        boss_scroll = QScrollArea()
        boss_scroll.setWidgetResizable(True)
        boss_scroll.setFixedHeight(200)
        boss_scroll.setStyleSheet("background-color: #181818; border: 1px solid #2a2a2a; border-radius: 4px;")
        boss_holder = QWidget()
        boss_col = QVBoxLayout(boss_holder)
        boss_col.setSpacing(2)
        boxes = {}
        for _path, key, display in _boss_files():
            cb = QCheckBox(display)
            cb.setStyleSheet("color: #cccccc; font-size: 12px;")
            boxes[key] = cb
            boss_col.addWidget(cb)
        boss_col.addStretch()
        boss_scroll.setWidget(boss_holder)
        outer.addWidget(boss_scroll)

        existing = QListWidget()
        existing.setStyleSheet("background-color: #181818; border: 1px solid #2a2a2a; border-radius: 4px;")
        existing.setFixedHeight(90)

        def refresh_existing():
            existing.clear()
            for it in self.custom_items:
                names = [d for _p, k, d in _boss_files() if k in it.get("bosses", [])]
                existing.addItem(f"{it['name']}  —  {', '.join(names) if names else 'no boss'}")

        refresh_existing()
        outer.addWidget(QLabel("Your custom items:"))
        outer.addWidget(existing)

        def remove_selected():
            row = existing.currentRow()
            if row < 0 or row >= len(self.custom_items):
                return
            item = self.custom_items[row]
            if QMessageBox.question(dialog, "Remove Item",
                                    f"Remove \"{item['name']}\"?\n\nIts image file stays in the assets folder.",
                                    ) != QMessageBox.StandardButton.Yes:
                return
            self.custom_items.pop(row)
            self._apply_custom_items()
            self.save_data()
            refresh_existing()

        btn_remove = QPushButton("Remove Selected")
        btn_remove.setStyleSheet(
            "QPushButton { background-color: #5a1a1a; color: #ff6666; border-radius: 3px; padding: 4px 8px; border: none; }"
            "QPushButton:hover { background-color: #7b2222; color: white; }")
        btn_remove.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_remove.clicked.connect(remove_selected)
        outer.addWidget(btn_remove)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Add Item")
        outer.addWidget(buttons)
        buttons.rejected.connect(dialog.reject)

        def commit():
            name = name_edit.text().strip()
            bosses = [k for k, cb in boxes.items() if cb.isChecked()]
            if not name:
                QMessageBox.warning(dialog, "Missing Name", "Give the item a name.")
                return
            if not chosen["path"]:
                QMessageBox.warning(dialog, "Missing Image", "Choose an image for the item.")
                return
            if not bosses:
                QMessageBox.warning(dialog, "No Boss", "Tick at least one boss that drops this item.")
                return
            dest_name = f"{name}.png"
            dest = os.path.join(ITEMS_ASSETS_DIR, dest_name)
            if os.path.exists(dest):
                QMessageBox.warning(dialog, "Name Taken",
                                    f"An item image named \"{dest_name}\" already exists. Pick another name.")
                return
            try:
                Image.open(chosen["path"]).convert("RGBA").save(dest)
            except (OSError, ValueError) as e:
                QMessageBox.critical(dialog, "Image Error", f"Could not read that image:\n{e}")
                return

            self.custom_items.append({"name": name, "file": dest_name, "bosses": bosses})
            _scaled_pixmap.cache_clear()
            self._apply_custom_items()
            self.save_data()
            self.update_overview_calendar()
            refresh_existing()
            name_edit.clear()
            chosen["path"] = None
            preview.setPixmap(QPixmap())
            preview.setText("no\nimage")
            for cb in boxes.values():
                cb.setChecked(False)

        buttons.accepted.connect(commit)
        dialog.exec()

    def _auto_populate_new_week(self):
        current_week_key = self.actual_current_week_key
        prev_week_key = (self.actual_current_thursday - timedelta(weeks=1)).strftime("%Y-%m-%d")

        changed = False
        for char in self.characters:
            cid = char["id"]
            if self.saved_boss_clears.get((cid, current_week_key)):
                continue
            # Monthly bosses (Black Mage) never auto-carry forward — they're marked done
            # explicitly, once per run, on whichever week the user checks them off.
            new_entries = [
                {"path": p, "difficulty": s["difficulty"], "party_size": s.get("party_size", 1), "cleared": False}
                for p, _k, _r, s, _i in self._active_bosses(cid, prev_week_key)
            ]
            if new_entries:
                self.saved_boss_clears[(cid, current_week_key)] = new_entries
                changed = True

        if changed:
            self.save_data()

    def setup_global_tab_bar(self):
        menu_frame = QFrame()
        menu_frame.setStyleSheet("background-color: #1a1a1a; border-bottom: 2px solid #282828;")
        menu_hbox = QHBoxLayout(menu_frame)
        menu_hbox.setContentsMargins(15, 10, 15, 10)
        menu_hbox.setSpacing(10)

        btn_style = """
            QPushButton {
                background-color: #282828; color: #b3b3b3; font-weight: bold; font-size: 13px;
                border: 1px solid #333; border-radius: 4px; padding: 6px 16px;
            }
            QPushButton:hover { background-color: #333; color: white; }
            QPushButton:checked { background-color: #e67e22; color: white; border: 1px solid #d35400; }
        """

        self.tab_tracker = QPushButton("Weekly Tracker")
        self.tab_tracker.setStyleSheet(btn_style)
        self.tab_tracker.setCheckable(True)
        self.tab_tracker.setChecked(True)

        self.tab_stats = QPushButton("Statistics")
        self.tab_stats.setStyleSheet(btn_style)
        self.tab_stats.setCheckable(True)

        self.tab_version_history = QPushButton("Version History")
        self.tab_version_history.setStyleSheet(btn_style)
        self.tab_version_history.setCheckable(True)

        self.tab_all_tasks = QPushButton("Tasks")
        self.tab_all_tasks.setStyleSheet(btn_style)
        self.tab_all_tasks.setCheckable(True)

        self.tab_item_results = QPushButton("Item Results")
        self.tab_item_results.setStyleSheet(btn_style)
        self.tab_item_results.setCheckable(True)

        self.tab_pitched_items = QPushButton("Star Force")
        self.tab_pitched_items.setStyleSheet(btn_style)
        self.tab_pitched_items.setCheckable(True)

        self.tab_item_scanner = QPushButton("Item Scanner")
        self.tab_item_scanner.setStyleSheet(btn_style)
        self.tab_item_scanner.setCheckable(True)

        self._tab_buttons = {
            0: self.tab_tracker, 2: self.tab_stats, 3: self.tab_version_history, 4: self.tab_all_tasks,
            5: self.tab_item_results, 6: self.tab_pitched_items, 7: self.tab_item_scanner,
        }
        for idx, btn in self._tab_buttons.items():
            btn.clicked.connect(lambda _checked, i=idx: self.switch_global_tab(i))

        menu_hbox.addWidget(self.tab_tracker)
        menu_hbox.addWidget(self.tab_stats)
        menu_hbox.addWidget(self.tab_all_tasks)
        menu_hbox.addWidget(self.tab_item_results)
        menu_hbox.addWidget(self.tab_pitched_items)
        if ENABLE_ITEM_SCANNER:
            menu_hbox.addWidget(self.tab_item_scanner)
        menu_hbox.addWidget(self.tab_version_history)
        menu_hbox.addStretch()

        font_size_lbl = QLabel("Label size:")
        font_size_lbl.setStyleSheet("color: #666666; font-size: 11px; padding-right: 2px;")
        menu_hbox.addWidget(font_size_lbl)

        btn_fs_minus = QPushButton("−")
        btn_fs_minus.setFixedSize(24, 24)
        btn_fs_minus.setStyleSheet(
            "QPushButton { background-color: #2a2a2a; color: #aaaaaa; border: 1px solid #3a3a3a; border-radius: 3px; font-size: 14px; font-weight: bold; }"
            "QPushButton:hover { background-color: #3a3a3a; color: white; }")
        btn_fs_minus.clicked.connect(lambda: self._change_label_font_size(-1))
        menu_hbox.addWidget(btn_fs_minus)

        self._font_size_display = QLabel(str(LABEL_FONT_SIZE))
        self._font_size_display.setStyleSheet("color: #e0e0e0; font-size: 12px; font-weight: bold; min-width: 22px; text-align: center;")
        self._font_size_display.setAlignment(Qt.AlignmentFlag.AlignCenter)
        menu_hbox.addWidget(self._font_size_display)

        btn_fs_plus = QPushButton("+")
        btn_fs_plus.setFixedSize(24, 24)
        btn_fs_plus.setStyleSheet(
            "QPushButton { background-color: #2a2a2a; color: #aaaaaa; border: 1px solid #3a3a3a; border-radius: 3px; font-size: 14px; font-weight: bold; }"
            "QPushButton:hover { background-color: #3a3a3a; color: white; }")
        btn_fs_plus.clicked.connect(lambda: self._change_label_font_size(1))
        menu_hbox.addWidget(btn_fs_plus)
        menu_hbox.addSpacing(10)

        ver_lbl = QLabel(APP_VERSION)
        ver_lbl.setStyleSheet("color: #444444; font-size: 10px; font-weight: bold; padding: 2px 6px;")
        menu_hbox.addWidget(ver_lbl)

        central_container = QWidget()
        self.setCentralWidget(central_container)
        self.root_vbox = QVBoxLayout(central_container)
        self.root_vbox.setContentsMargins(0, 0, 0, 0)
        self.root_vbox.setSpacing(0)
        self.root_vbox.addWidget(menu_frame)

        self.inline_calendar_drawer = QCalendarWidget()
        self.inline_calendar_drawer.setGridVisible(True)
        self.inline_calendar_drawer.setStyleSheet("""
            QCalendarWidget QWidget { alternate-background-color: #252525; background-color: #1c1c1c; }
            QCalendarWidget QAbstractItemView:enabled { color: #e0e0e0; background-color: #1c1c1c; selection-background-color: #e67e22; selection-color: white; }
            QCalendarWidget QMenu { background-color: #1a1a1a; color: white; }
            QCalendarWidget #qt_calendar_navigationbar { background-color: #1a1a1a; padding: 4px; }
            QCalendarWidget QToolButton { color: #e0e0e0; background-color: #2a2a2a; border: 1px solid #3a3a3a; border-radius: 4px; padding: 3px 8px; font-weight: bold; font-size: 13px; }
            QCalendarWidget QToolButton:hover { background-color: #e67e22; color: white; }
            QCalendarWidget QSpinBox { color: #e0e0e0; background-color: #2a2a2a; border: 1px solid #3a3a3a; border-radius: 4px; padding: 2px; font-size: 13px; }
        """)
        self.inline_calendar_drawer.setFixedHeight(220)
        self.inline_calendar_drawer.setVisible(False)
        self.inline_calendar_drawer.activated.connect(self.handle_inline_date_jump)

        self.root_vbox.addWidget(self.inline_calendar_drawer)
        self.root_vbox.addWidget(self.view_stack)

    def switch_global_tab(self, stack_idx):
        self.inline_calendar_drawer.setVisible(False)
        for idx, btn in self._tab_buttons.items():
            btn.setChecked(idx == stack_idx)
        if stack_idx == 0:
            self.return_to_overview()
            return
        self.view_stack.setCurrentIndex(stack_idx)
        refresh = {
            2: self.update_statistics_charts, 4: self.update_all_tasks_page,
            5: self.update_item_results_page, 6: self.update_pitched_items_page,
        }.get(stack_idx)
        if refresh:
            refresh()

    def _change_label_font_size(self, delta):
        global LABEL_FONT_SIZE
        LABEL_FONT_SIZE = max(8, min(24, LABEL_FONT_SIZE + delta))
        self._font_size_display.setText(str(LABEL_FONT_SIZE))
        self.save_data()
        self.refresh_active_view()

    def toggle_inline_calendar(self):
        self.inline_calendar_drawer.setVisible(not self.inline_calendar_drawer.isVisible())

    def handle_inline_date_jump(self, qdate):
        selected_date = qdate.toPyDate()
        target_thursday = selected_date - timedelta(days=(selected_date.weekday() - 3) % 7)
        delta_days = (target_thursday - self.base_thursday).days
        self.view_week_offset = delta_days // 7
        self.inline_calendar_drawer.setVisible(False)
        self.refresh_active_view()

    def build_overview_page(self):
        page = QWidget()
        main_hbox = QHBoxLayout(page)
        left_vbox = QVBoxLayout()
        header = QHBoxLayout()

        title = QLabel("Weekly Boss Drop Tracker")
        title.setStyleSheet("color: #e67e22; font-size: 20px; font-weight: bold;")
        header.addWidget(title)
        header.addStretch()

        nav_style = "QPushButton { background-color: #e67e22; color: white; border-radius: 4px; padding: 5px 14px; font-weight: bold; font-size: 14px; } QPushButton:hover { background-color: #d35400; }"
        btn_p = QPushButton("<")
        btn_p.setStyleSheet(nav_style)
        btn_p.clicked.connect(lambda: self.shift_weeks(-1))
        header.addWidget(btn_p)

        btn_n = QPushButton(">")
        btn_n.setStyleSheet(nav_style)
        btn_n.clicked.connect(lambda: self.shift_weeks(1))
        header.addWidget(btn_n)

        btn_jump = QPushButton("Jump to Date")
        btn_jump.setStyleSheet(
            "QPushButton { background-color: #e67e22; color: white; border-radius: 4px; padding: 5px 12px; font-weight: bold; font-size: 13px; } QPushButton:hover { background-color: #d35400; }")
        btn_jump.clicked.connect(self.toggle_inline_calendar)
        header.addWidget(btn_jump)

        btn_this_week = QPushButton("This Week")
        btn_this_week.setStyleSheet(
            "QPushButton { background-color: #2980b9; color: white; border-radius: 4px; padding: 5px 12px; font-weight: bold; font-size: 13px; } QPushButton:hover { background-color: #1f6391; }")
        btn_this_week.clicked.connect(self.jump_to_current_week)
        header.addWidget(btn_this_week)
        header.addSpacing(10)

        btn_add = QPushButton("+ New Character")
        btn_add.setStyleSheet(
            "QPushButton { background-color: #3a3a3a; color: white; border-radius: 4px; padding: 6px 12px; font-weight: bold; font-size: 13px; } QPushButton:hover { background-color: #4a4a4a; }")
        btn_add.clicked.connect(self.add_character_dialog)
        header.addWidget(btn_add)

        btn_clear_items = QPushButton("Clear All Items")
        btn_clear_items.setStyleSheet(
            "QPushButton { background-color: #7b2222; color: white; border-radius: 4px; padding: 6px 12px; font-weight: bold; font-size: 13px; } QPushButton:hover { background-color: #a02828; }")
        btn_clear_items.clicked.connect(self.handle_clear_all_items)
        header.addWidget(btn_clear_items)

        btn_complete_all = QPushButton("Complete All")
        btn_complete_all.setStyleSheet(
            "QPushButton { background-color: #1a5c1a; color: #2ecc71; border-radius: 4px; padding: 6px 12px; font-weight: bold; font-size: 13px; border: 1px solid #2ecc71; } QPushButton:hover { background-color: #1e7a1e; color: white; }")
        btn_complete_all.clicked.connect(self.complete_all_characters)
        header.addWidget(btn_complete_all)
        left_vbox.addLayout(header)

        self.completed_summary_label = QLabel("")
        self.completed_summary_label.setStyleSheet("color: #2ecc71; font-size: 12px; font-weight: bold; padding: 2px 0 4px 2px;")
        left_vbox.addWidget(self.completed_summary_label)

        self.crystals_sold_label = QLabel("")
        self.crystals_sold_label.setStyleSheet("color: #f0c040; font-size: 12px; font-weight: bold; padding: 0 0 4px 2px;")
        left_vbox.addWidget(self.crystals_sold_label)

        self.completed_summary_excluded_label = QLabel("")
        self.completed_summary_excluded_label.setStyleSheet("color: #999999; font-size: 12px; font-weight: bold; padding: 0 0 4px 2px;")
        self.completed_summary_excluded_label.setVisible(False)
        left_vbox.addWidget(self.completed_summary_excluded_label)

        _ov_container = QWidget()
        _ov_container.setStyleSheet("background-color: transparent;")
        self.overview_grid = QGridLayout(_ov_container)
        self.overview_grid.setSpacing(8)
        self.overview_grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        _ov_scroll = QScrollArea()
        _ov_scroll.setWidgetResizable(True)
        _ov_scroll.setStyleSheet("background-color: transparent; border: none;")
        _ov_scroll.setWidget(_ov_container)
        left_vbox.addWidget(_ov_scroll)
        main_hbox.addLayout(left_vbox, stretch=4)

        right_panel = QFrame()
        right_panel.setFixedWidth(260)
        right_panel.setStyleSheet("background-color: #181818; border: 1px solid #232323; border-radius: 6px;")
        panel_layout = QVBoxLayout(right_panel)

        tray_head = QHBoxLayout()
        lbl_tray = QLabel("Item Inventory")
        lbl_tray.setStyleSheet("color: #e67e22; font-size: 14px; font-weight: bold; padding: 2px;")
        tray_head.addWidget(lbl_tray)
        tray_head.addStretch()
        btn_custom = QPushButton("＋ Custom")
        btn_custom.setToolTip("Add your own item with an image and the bosses that drop it")
        btn_custom.setStyleSheet(
            "QPushButton { background-color: #1a4a2a; color: #2ecc71; border-radius: 3px;"
            " padding: 3px 8px; font-size: 11px; border: none; }"
            "QPushButton:hover { background-color: #216b3c; color: white; }")
        btn_custom.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_custom.clicked.connect(self.add_custom_item_dialog)
        tray_head.addWidget(btn_custom)
        panel_layout.addLayout(tray_head)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background-color: transparent; border: none;")

        self.items_shelf_layout = QGridLayout()
        self.items_shelf_layout.setSpacing(6)
        self.items_shelf_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        self._populate_items_shelf()

        tray_widget = QWidget()
        tray_widget.setLayout(self.items_shelf_layout)
        scroll.setWidget(tray_widget)
        panel_layout.addWidget(scroll)
        main_hbox.addWidget(right_panel, stretch=1)
        self.view_stack.addWidget(page)

    def build_boss_schedule_page(self):
        page = QWidget()
        main_hbox = QHBoxLayout(page)
        left_vbox = QVBoxLayout()
        header = QHBoxLayout()

        self.boss_page_title = QLabel("Character Schedule")
        self.boss_page_title.setStyleSheet("color: #ff9900; font-size: 20px; font-weight: bold;")
        header.addWidget(self.boss_page_title)
        header.addStretch()

        nav_style = "QPushButton { background-color: #e67e22; color: white; border-radius: 4px; padding: 5px 14px; font-weight: bold; font-size: 14px; } QPushButton:hover { background-color: #d35400; }"
        btn_p = QPushButton("<")
        btn_p.setStyleSheet(nav_style)
        btn_p.clicked.connect(lambda: self.shift_weeks(-1))
        header.addWidget(btn_p)

        btn_n = QPushButton(">")
        btn_n.setStyleSheet(nav_style)
        btn_n.clicked.connect(lambda: self.shift_weeks(1))
        header.addWidget(btn_n)

        btn_jump = QPushButton("Jump to Date")
        btn_jump.setStyleSheet(
            "QPushButton { background-color: #e67e22; color: white; border-radius: 4px; padding: 5px 12px; font-weight: bold; font-size: 13px; } QPushButton:hover { background-color: #d35400; }")
        btn_jump.clicked.connect(self.toggle_inline_calendar)
        header.addWidget(btn_jump)

        btn_this_week = QPushButton("This Week")
        btn_this_week.setStyleSheet(
            "QPushButton { background-color: #2980b9; color: white; border-radius: 4px; padding: 5px 12px; font-weight: bold; font-size: 13px; } QPushButton:hover { background-color: #1f6391; }")
        btn_this_week.clicked.connect(self.jump_to_current_week)
        header.addWidget(btn_this_week)

        btn_add_all = QPushButton("+ Add All Bosses to Week")
        btn_add_all.setStyleSheet(
            "QPushButton { background-color: #27ae60; color: white; border-radius: 4px; padding: 5px 12px; font-weight: bold; font-size: 13px; } QPushButton:hover { background-color: #1e8449; }")
        btn_add_all.clicked.connect(self.handle_add_all_bosses_to_date)
        header.addWidget(btn_add_all)

        btn_clear_bosses = QPushButton("Clear All Bosses")
        btn_clear_bosses.setStyleSheet(
            "QPushButton { background-color: #7b2222; color: white; border-radius: 4px; padding: 5px 12px; font-weight: bold; font-size: 13px; } QPushButton:hover { background-color: #a02828; }")
        btn_clear_bosses.clicked.connect(self.handle_clear_all_bosses)
        header.addWidget(btn_clear_bosses)

        btn_presets = QPushButton("Presets")
        btn_presets.setStyleSheet(
            "QPushButton { background-color: #6a3a8a; color: white; border-radius: 4px; padding: 5px 12px; font-weight: bold; font-size: 13px; } QPushButton:hover { background-color: #7b4a9a; }")
        btn_presets.clicked.connect(self.handle_presets_dialog)
        header.addWidget(btn_presets)
        header.addSpacing(15)

        btn_back = QPushButton("← Back to Overview")
        btn_back.setStyleSheet(
            "QPushButton { background-color: #3a3a3a; color: white; border-radius: 4px; padding: 6px 14px; font-weight: bold; } QPushButton:hover { background-color: #4a4a4a; }")
        btn_back.clicked.connect(self.return_to_overview)
        header.addWidget(btn_back)
        left_vbox.addLayout(header)

        self.boss_grid = QGridLayout()
        self.boss_grid.setSpacing(8)
        left_vbox.addLayout(self.boss_grid)

        stats_tabs = QTabWidget()
        self.boss_schedule_stats_tabs = stats_tabs
        stats_tabs.setStyleSheet(
            "QTabWidget::pane { background: #181818; border: 1px solid #232323; border-radius: 4px; }"
            "QTabBar::tab { background: #2a2a2a; color: #aaaaaa; padding: 4px 12px; font-size: 12px; }"
            "QTabBar::tab:selected { background: #181818; color: #f0c040; border-bottom: 2px solid #f0c040; }"
        )

        history_widget = QWidget()
        history_layout = QVBoxLayout(history_widget)
        history_layout.setContentsMargins(6, 6, 6, 4)
        history_layout.setSpacing(4)
        lbl_history = QLabel("Monthly Crystal Meso — Last 6 Months")
        lbl_history.setStyleSheet("color: #e67e22; font-size: 12px; font-weight: bold;")
        history_layout.addWidget(lbl_history)
        self.meso_chart = MesoBarChart()
        history_layout.addWidget(self.meso_chart)
        stats_tabs.addTab(history_widget, "Meso History")

        totals_widget = QWidget()
        totals_layout = QVBoxLayout(totals_widget)
        totals_layout.setContentsMargins(6, 6, 6, 4)
        totals_layout.setSpacing(4)
        self.char_grindstone_label = QLabel("Grindstones from Ring Boxes: 0")
        self.char_grindstone_label.setStyleSheet("color: #66ccff; font-size: 12px; font-weight: bold;")
        totals_layout.addWidget(self.char_grindstone_label)
        self.boss_totals_table = QTableWidget(0, 3)
        self.boss_totals_table.setHorizontalHeaderLabels(["Boss", "Clears", "Items Earned"])
        self.boss_totals_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.boss_totals_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.boss_totals_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.boss_totals_table.horizontalHeader().setStyleSheet("color: #aaaaaa; font-size: 12px;")
        self.boss_totals_table.verticalHeader().setVisible(False)
        self.boss_totals_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.boss_totals_table.setStyleSheet(
            "QTableWidget { background-color: #1a1a1a; color: white; border: none; gridline-color: #2a2a2a; font-size: 12px; }"
            "QHeaderView::section:hover { background-color: #555555; }"
            "QTableWidget::item { padding: 2px 6px; }"
        )
        self.boss_totals_table.setSortingEnabled(True)
        self.boss_totals_table.horizontalHeader().setSectionsClickable(True)
        totals_layout.addWidget(self.boss_totals_table)
        stats_tabs.addTab(totals_widget, "Boss Totals")

        rates_widget = QWidget()
        rates_layout = QVBoxLayout(rates_widget)
        rates_layout.setContentsMargins(6, 6, 6, 4)
        rates_layout.setSpacing(4)
        char_filter_widget, self.char_drop_cat_cbs = self._make_cat_filter_row()
        rates_layout.addWidget(char_filter_widget)
        self.drop_rates_table = QTableWidget(0, 4)
        self.drop_rates_table.setHorizontalHeaderLabels(["Item", "Boss (Diff)", "Got / Clears", "Rate %"])
        self.drop_rates_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.drop_rates_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.drop_rates_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.drop_rates_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.drop_rates_table.horizontalHeader().setStyleSheet("color: #aaaaaa; font-size: 12px;")
        self.drop_rates_table.verticalHeader().setVisible(False)
        self.drop_rates_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.drop_rates_table.setStyleSheet(
            "QTableWidget { background-color: #1a1a1a; color: white; border: none; gridline-color: #2a2a2a; font-size: 12px; }"
            "QHeaderView::section:hover { background-color: #555555; }"
            "QTableWidget::item { padding: 2px 6px; }"
        )
        self.drop_rates_table.setSortingEnabled(True)
        self.drop_rates_table.horizontalHeader().setSectionsClickable(True)
        rates_layout.addWidget(self.drop_rates_table)
        for _cb in self.char_drop_cat_cbs.values():
            _cb.stateChanged.connect(lambda _: self._apply_drop_filter(self.drop_rates_table, self.char_drop_cat_cbs))
        stats_tabs.addTab(rates_widget, "Drop Rates")

        tasks_widget = QWidget()
        tasks_layout = QVBoxLayout(tasks_widget)
        tasks_layout.setContentsMargins(6, 6, 6, 4)
        tasks_layout.setSpacing(6)

        self.char_tasks_header = QLabel("Tasks")
        self.char_tasks_header.setStyleSheet("color: #e67e22; font-size: 12px; font-weight: bold;")
        tasks_layout.addWidget(self.char_tasks_header)

        task_btn_row = QHBoxLayout()
        btn_add_task = QPushButton("+ Add Task")
        btn_add_task.setStyleSheet(
            "QPushButton { background-color: #27ae60; color: white; border-radius: 3px; padding: 3px 10px; font-size: 12px; font-weight: bold; }"
            "QPushButton:hover { background-color: #1e8449; }")
        btn_add_task.clicked.connect(self._add_char_task)
        task_btn_row.addWidget(btn_add_task)
        task_btn_row.addStretch()
        self._char_tasks_sort_combo = self._make_sort_combo(self.tasks_sort_mode, self._set_tasks_sort_mode)
        task_btn_row.addWidget(self._char_tasks_sort_combo)
        tasks_layout.addLayout(task_btn_row)

        self._char_tasks_tabs = QTabWidget()
        self._char_tasks_tabs.setStyleSheet(
            "QTabWidget::pane { border: 1px solid #2d2d2d; background: #1a1a1a; }"
            "QTabBar::tab { background: #222222; color: #aaaaaa; padding: 4px 12px; font-size: 12px; }"
            "QTabBar::tab:selected { background: #1a1a1a; color: #e67e22; border-bottom: 2px solid #e67e22; }"
            "QTabBar::tab:hover { background: #2a2a2a; }")
        for lay_attr, cont_attr, label in (
            ("_char_todo_layout", "_char_todo_container", "To Do"),
            ("_char_done_layout", "_char_done_container", "Completed"),
        ):
            sc = QScrollArea()
            sc.setWidgetResizable(True)
            sc.setStyleSheet("background: transparent; border: none;")
            cont = QWidget()
            cont.setStyleSheet("background-color: #1a1a1a;")
            lay = QVBoxLayout(cont)
            lay.setContentsMargins(8, 6, 8, 6)
            lay.setSpacing(4)
            lay.setAlignment(Qt.AlignmentFlag.AlignTop)
            sc.setWidget(cont)
            setattr(self, lay_attr, lay)
            setattr(self, cont_attr, cont)
            cont.installEventFilter(self)
            self._char_tasks_tabs.addTab(sc, label)
        tasks_layout.addWidget(self._char_tasks_tabs)
        stats_tabs.addTab(tasks_widget, "Tasks")

        item_results_widget = QWidget()
        item_results_layout = QVBoxLayout(item_results_widget)
        item_results_layout.setContentsMargins(6, 6, 6, 4)
        item_results_layout.setSpacing(6)

        self.char_item_results_header = QLabel("Item Results")
        self.char_item_results_header.setStyleSheet("color: #5599cc; font-size: 12px; font-weight: bold;")
        item_results_layout.addWidget(self.char_item_results_header)

        result_btn_row = QHBoxLayout()
        btn_add_result = QPushButton("+ Add Result")
        btn_add_result.setStyleSheet(
            "QPushButton { background-color: #1a2a3a; color: #5599cc; border-radius: 3px; padding: 3px 10px; font-size: 12px; font-weight: bold; border: 1px solid #5599cc; }"
            "QPushButton:hover { background-color: #253545; }")
        btn_add_result.clicked.connect(self._add_char_item_result)
        result_btn_row.addWidget(btn_add_result)
        result_btn_row.addStretch()
        self._char_items_sort_combo = self._make_sort_combo(self.item_results_sort_mode, self._set_item_results_sort_mode)
        result_btn_row.addWidget(self._char_items_sort_combo)
        item_results_layout.addLayout(result_btn_row)

        self._char_item_results_tabs = QTabWidget()
        self._char_item_results_tabs.setStyleSheet(
            "QTabWidget::pane { border: 1px solid #2d2d2d; background: #1a1a1a; }"
            "QTabBar::tab { background: #222222; color: #aaaaaa; padding: 4px 12px; font-size: 12px; }"
            "QTabBar::tab:selected { background: #1a1a1a; color: #5599cc; border-bottom: 2px solid #5599cc; }"
            "QTabBar::tab:hover { background: #2a2a2a; }")
        for lay_attr, cont_attr, label in (
            ("_char_item_results_todo_layout", "_char_item_results_todo_container", "Uncompleted"),
            ("_char_item_results_done_layout", "_char_item_results_done_container", "Completed"),
        ):
            sc = QScrollArea()
            sc.setWidgetResizable(True)
            sc.setStyleSheet("background: transparent; border: none;")
            cont = QWidget()
            cont.setStyleSheet("background-color: #1a1a1a;")
            lay = QVBoxLayout(cont)
            lay.setContentsMargins(8, 6, 8, 6)
            lay.setSpacing(4)
            lay.setAlignment(Qt.AlignmentFlag.AlignTop)
            sc.setWidget(cont)
            setattr(self, lay_attr, lay)
            setattr(self, cont_attr, cont)
            self._char_item_results_tabs.addTab(sc, label)
        item_results_layout.addWidget(self._char_item_results_tabs)
        stats_tabs.addTab(item_results_widget, "Item Results")

        left_vbox.addWidget(stats_tabs, stretch=1)
        main_hbox.addLayout(left_vbox, stretch=4)

        self.boss_panel_frame = QFrame()
        self.boss_panel_frame.setFixedWidth(260)
        self.boss_panel_frame.setStyleSheet("background-color: #181818; border: 1px solid #232323; border-radius: 6px;")
        panel_layout = QVBoxLayout(self.boss_panel_frame)

        lbl_tray = QLabel("Boss Listing")
        lbl_tray.setStyleSheet("color: #ff9900; font-size: 14px; font-weight: bold; padding: 2px;")
        panel_layout.addWidget(lbl_tray)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background-color: transparent; border: none;")

        self.boss_shelf_layout = QGridLayout()
        self.boss_shelf_layout.setSpacing(6)
        self.boss_shelf_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        tray_widget = QWidget()
        tray_widget.setLayout(self.boss_shelf_layout)
        scroll.setWidget(tray_widget)
        panel_layout.addWidget(scroll)

        meso_frame = QFrame()
        meso_frame.setStyleSheet("background-color: #1c1c1c; border: 1px solid #333333; border-radius: 4px;")
        meso_layout = QVBoxLayout(meso_frame)
        meso_layout.setContentsMargins(10, 8, 10, 8)
        meso_layout.setSpacing(4)
        lbl_meso_title = QLabel("Monthly Crystal Meso")
        lbl_meso_title.setStyleSheet("color: #e67e22; font-size: 12px; font-weight: bold; background: transparent; border: none;")
        meso_layout.addWidget(lbl_meso_title)
        self.lbl_monthly_meso = QLabel("—")
        self.lbl_monthly_meso.setStyleSheet("color: #f0c040; font-size: 15px; font-weight: bold; background: transparent; border: none;")
        meso_layout.addWidget(self.lbl_monthly_meso)
        panel_layout.addWidget(meso_frame)

        main_hbox.addWidget(self.boss_panel_frame, stretch=1)
        self.view_stack.addWidget(page)

    def build_statistics_dashboard_page(self):
        page = QWidget()
        page.setStyleSheet("background-color: #121212;")

        tab_widget = QTabWidget()
        tab_widget.setStyleSheet(
            "QTabWidget::pane { background: #121212; border: none; }"
            "QTabBar::tab { background: #2a2a2a; color: #aaaaaa; padding: 6px 20px; font-size: 13px; }"
            "QTabBar::tab:selected { background: #121212; color: #f0c040; border-bottom: 2px solid #f0c040; }"
        )

        table_style = (
            "QTableWidget { background-color: #1c1c1c; color: #e0e0e0; gridline-color: #2d2d2d;"
            " border: 1px solid #2d2d2d; border-radius: 4px; font-size: 13px; }"
            "QHeaderView::section { background-color: #e67e22; color: white; font-weight: bold;"
            " border: 1px solid #2d2d2d; padding: 5px; font-size: 13px; }"
            "QHeaderView::section:hover { background-color: #d35400; }"
            "QTableWidget::item { padding: 4px; }"
        )

        # ── Tab 1: Meso Income ──────────────────────────────────────────
        meso_scroll = QScrollArea()
        meso_scroll.setWidgetResizable(True)
        meso_scroll.setStyleSheet("background: transparent; border: none;")
        meso_content = QWidget()
        meso_content.setStyleSheet("background-color: #121212;")
        meso_layout = QVBoxLayout(meso_content)
        meso_layout.setContentsMargins(20, 15, 20, 20)
        meso_layout.setSpacing(20)

        lbl_weekly = QLabel("Weekly Crystal Meso — All Characters (Last 8 Weeks)")
        lbl_weekly.setStyleSheet("color: #e67e22; font-size: 15px; font-weight: bold;")
        meso_layout.addWidget(lbl_weekly)
        self.stats_weekly_chart = MesoBarChart()
        self.stats_weekly_chart.setFixedHeight(180)
        meso_layout.addWidget(self.stats_weekly_chart)
        self.stats_weekly_table = QTableWidget(0, 3)
        self.stats_weekly_table.setHorizontalHeaderLabels(["Week", "Total Crystals (All Chars)", "Total Meso (All Chars)"])
        self.stats_weekly_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.stats_weekly_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.stats_weekly_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.stats_weekly_table.verticalHeader().setVisible(False)
        self.stats_weekly_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.stats_weekly_table.setFixedHeight(220)
        self.stats_weekly_table.setStyleSheet(table_style)
        meso_layout.addWidget(self.stats_weekly_table)

        lbl_monthly = QLabel("Monthly Crystal Meso — All Characters (Last 6 Months)")
        lbl_monthly.setStyleSheet("color: #e67e22; font-size: 15px; font-weight: bold;")
        meso_layout.addWidget(lbl_monthly)
        self.stats_monthly_chart = MesoBarChart()
        self.stats_monthly_chart.setFixedHeight(180)
        meso_layout.addWidget(self.stats_monthly_chart)
        self.stats_monthly_table = QTableWidget(0, 3)
        self.stats_monthly_table.setHorizontalHeaderLabels(["Month", "Total Crystals (All Chars)", "Total Meso (All Chars)"])
        self.stats_monthly_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.stats_monthly_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.stats_monthly_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.stats_monthly_table.verticalHeader().setVisible(False)
        self.stats_monthly_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.stats_monthly_table.setFixedHeight(180)
        self.stats_monthly_table.setStyleSheet(table_style)
        meso_layout.addWidget(self.stats_monthly_table)

        lbl_bm_monthly = QLabel("Monthly Black Mage Meso — All Characters (Last 6 Months)")
        lbl_bm_monthly.setStyleSheet("color: #bf55ec; font-size: 15px; font-weight: bold;")
        meso_layout.addWidget(lbl_bm_monthly)
        self.stats_bm_monthly_chart = MesoBarChart()
        self.stats_bm_monthly_chart.setFixedHeight(180)
        meso_layout.addWidget(self.stats_bm_monthly_chart)
        self.stats_bm_monthly_table = QTableWidget(0, 2)
        self.stats_bm_monthly_table.setHorizontalHeaderLabels(["Month", "Total Meso (All Chars)"])
        self.stats_bm_monthly_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.stats_bm_monthly_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.stats_bm_monthly_table.verticalHeader().setVisible(False)
        self.stats_bm_monthly_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.stats_bm_monthly_table.setFixedHeight(180)
        self.stats_bm_monthly_table.setStyleSheet(table_style)
        meso_layout.addWidget(self.stats_bm_monthly_table)

        meso_scroll.setWidget(meso_content)
        tab_widget.addTab(meso_scroll, "Meso Income")

        # ── Tab 2: Boss Clears ──────────────────────────────────────────
        clears_scroll = QScrollArea()
        clears_scroll.setWidgetResizable(True)
        clears_scroll.setStyleSheet("background: transparent; border: none;")
        clears_content = QWidget()
        clears_content.setStyleSheet("background-color: #121212;")
        clears_layout = QVBoxLayout(clears_content)
        clears_layout.setContentsMargins(20, 15, 20, 20)
        clears_layout.setSpacing(20)

        lbl_totals = QLabel("Total Boss Clears — All Characters")
        lbl_totals.setStyleSheet("color: #e67e22; font-size: 15px; font-weight: bold;")
        clears_layout.addWidget(lbl_totals)
        self.stats_boss_totals_table = QTableWidget(0, 3)
        self.stats_boss_totals_table.setHorizontalHeaderLabels(["Boss", "Clears", "Items Earned"])
        self.stats_boss_totals_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.stats_boss_totals_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.stats_boss_totals_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.stats_boss_totals_table.verticalHeader().setVisible(False)
        self.stats_boss_totals_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.stats_boss_totals_table.setStyleSheet(table_style)
        self.stats_boss_totals_table.setSortingEnabled(True)
        self.stats_boss_totals_table.horizontalHeader().setSectionsClickable(True)
        clears_layout.addWidget(self.stats_boss_totals_table)

        lbl_rates = QLabel("Item Drop Rates — All Characters")
        lbl_rates.setStyleSheet("color: #e67e22; font-size: 15px; font-weight: bold;")
        clears_layout.addWidget(lbl_rates)
        stats_filter_widget, self.stats_drop_cat_cbs = self._make_cat_filter_row()
        clears_layout.addWidget(stats_filter_widget)
        self.stats_drop_rates_table = QTableWidget(0, 4)
        self.stats_drop_rates_table.setHorizontalHeaderLabels(["Item", "Boss (Diff)", "Got / Clears", "Rate %"])
        self.stats_drop_rates_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.stats_drop_rates_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.stats_drop_rates_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.stats_drop_rates_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.stats_drop_rates_table.verticalHeader().setVisible(False)
        self.stats_drop_rates_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.stats_drop_rates_table.setStyleSheet(table_style)
        self.stats_drop_rates_table.setSortingEnabled(True)
        self.stats_drop_rates_table.horizontalHeader().setSectionsClickable(True)
        clears_layout.addWidget(self.stats_drop_rates_table)
        for _cb in self.stats_drop_cat_cbs.values():
            _cb.stateChanged.connect(lambda _: self._apply_drop_filter(self.stats_drop_rates_table, self.stats_drop_cat_cbs))

        lbl_grindstone = QLabel("Grindstone of Life — Converted from Ring Boxes")
        lbl_grindstone.setStyleSheet("color: #66ccff; font-size: 15px; font-weight: bold;")
        clears_layout.addWidget(lbl_grindstone)
        self.stats_grindstone_table = QTableWidget(0, 4)
        self.stats_grindstone_table.setHorizontalHeaderLabels(["Character", "Ring Boxes", "Grindstones", "% Converted"])
        self.stats_grindstone_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.stats_grindstone_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.stats_grindstone_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.stats_grindstone_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.stats_grindstone_table.verticalHeader().setVisible(False)
        self.stats_grindstone_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.stats_grindstone_table.setStyleSheet(table_style)
        clears_layout.addWidget(self.stats_grindstone_table)

        clears_scroll.setWidget(clears_content)
        tab_widget.addTab(clears_scroll, "Boss Clears")

        root = QVBoxLayout(page)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(tab_widget)
        self.view_stack.addWidget(page)

    def build_version_history_page(self):
        page = QWidget()
        page.setStyleSheet("background-color: #121212;")

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background: transparent; border: none;")

        content = QWidget()
        content.setStyleSheet("background-color: #121212;")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(30, 20, 30, 30)
        layout.setSpacing(24)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        title = QLabel("Version History")
        title.setStyleSheet("color: #e67e22; font-size: 22px; font-weight: bold;")
        layout.addWidget(title)

        versions = [
            ("v1.30", "2026-09-23", [
                "Original Sin of Pride is now grouped under Brilliant in the Item Inventory and the drop-rate category filters, instead of falling into Others.",
            ]),
            ("v1.29", "2026-09-23", [
                "Added Hard Jupiter (5,953,000,000 crystal meso), dropping Grindstone of Faith, Eternal Armor Box (Limbo), Life Boss Ring Box and the new Original Sin of Pride. Normal Jupiter is unchanged and still drops Grindstone of Faith only.",
                "Replaced Jupiter's boss icon with its in-game portrait.",
            ]),
            ("v1.28", "2026-09-23", [
                "Added '+ Custom' next to the Item Inventory: add your own item with a name, an image and a tick list of the bosses that drop it — one item can be tied to several bosses. Custom items show up in drop-rate statistics, the boss totals table and the drop-source picker exactly like built-in ones, and can be removed again from the same dialog.",
                "The Eternal gear pieces no longer crowd the Item Inventory — only the two Eternal Armor Boxes are listed. The files are untouched, so icons already placed on a calendar still show.",
                "Removed the white inventory-tile background from DayBreak, Slime Ring, Mitra Rage, Blissful Nightmare, both Eternal Armor Boxes and Life Boss Ring Box.",
            ]),
            ("v1.27", "2026-09-22", [
                "Changing a boss's difficulty or party size, or removing it, in a past week now asks first whether the change applies to that week only or to every week through today. Previously it always silently carried forward. Current and future weeks are unaffected and never ask.",
            ]),
            ("v1.26", "2026-09-15", [
                "Internal cleanup: boss icons and the boss file listing are now cached, so redrawing the calendar does less work.",
            ]),
            ("v1.25", "2026-08-22", [
                "Added an 'Item Scanner' tab: press F9 anywhere (e.g. while hovering an item's tooltip in-game) to capture the screen instantly, without needing to move the mouse off the item first — the old flow required clicking a button, which meant the tooltip was already gone by the time the screenshot happened.",
                "The captured screenshot is auto-scanned for the tooltip's region near the cursor and cropped automatically; when it isn't confident, it falls back to letting you drag a box manually over the (already frozen) screenshot.",
                "Stats (STR/DEX/INT/LUK, All Stats, Max HP, Attack Power, Magic ATT, Defense, Potential, Required Job/Level) are read out with Windows' built-in OCR (no extra installs) and shown in the tab alongside the captured thumbnail and the raw OCR text, since OCR on small game fonts isn't perfect.",
            ]),
            ("v1.24", "2026-08-18", [
                "Added 7 new Star Force items — Eternal Hat, Eternal Top, Eternal Bottom, Eternal Shoulder, Eternal Cape, Eternal Glove, Eternal Boots — with their own extracted icons, selectable from '+ Add Item' with the full existing source/star/log system.",
            ]),
            ("v1.23", "2026-08-16", [
                "Dropping an item into the calendar with no matching boss on that week's roster now grey's it out automatically (ignored / won't count) instead of leaving it as a normal counted drop with no source.",
                "Fixed Black Mage's monthly Crystal Meso total being stuck at 0 (or not updating) on the Statistics dashboard whenever that character's current week hadn't been marked 'Done' yet — checking Black Mage is itself the confirmation, so it no longer waits on an unrelated weekly completion flag.",
                "Right-clicking the Black Mage checkmark on the Overview page now opens an edit dialog to change that month's difficulty/party size, instead of removing the check.",
                "Added a new 'Star Force' tab (top nav, next to Item Results) for tracking pitched items per character: opt-in — pick which characters to track with '+ Add Character', and which items to track per character with '+ Add Item' (choose from known pitched items or add a custom one with an optional custom icon).",
                "Each tracked item shows 5 source counters (Drops, Trace Restoration, Pitched Star Core, Pitched Whispers, Pitched Box — icons pulled from the reference image provided) and a star-level tracker, all with +/- steppers; item names can be renamed in place (e.g. for tracking two copies of the same item).",
                "Added 'Reset' and '→ 22' buttons next to each item's star box to jump straight to 0 or 22 stars.",
                "Adding any of the 5 sources now counts as a destruction (shown as a skull count under the star box) without resetting the star or interrupting the current attempt; right-clicking the star box still logs a full destruction that resets the star to 0.",
                "Added a per-item change log (📜 Log button) grouped by star level — everything logged while sitting at a given star collects under that star's heading, and successfully advancing to the next star seals that heading with its final destruction count and opens a fresh one. Individual log lines can be deleted (e.g. to undo a misclick).",
                "Removed the redundant per-item and per-character Σ total displays on the Star Force tab now that every source addition already counts 1:1 toward the destruction total.",
            ]),
            ("v1.22", "2026-08-16", [
                "Item drop assignment: the boss picker no longer lets the same boss be credited with more than one copy of the same item in the same week — bosses drop out of the list as they're used up, and once every matching boss has already been credited, adding another copy is blocked with a 'No Bosses Left' warning instead of guessing.",
                "When only one boss can still be credited for an item drop, it's now assigned automatically without a confirmation dialog — the dialog only appears when there's an actual choice to make.",
                "Black Mage is no longer draggable from the boss panel. It's now marked done from a checkmark next to each character's name on the Overview page: checking it for the first time ever asks for difficulty and party size, and every time after that it silently reuses whatever was used last time.",
                "Black Mage clears are now capped at once per real calendar month instead of once per week, and each clear remembers exactly which month it belongs to — so a clear made on, say, the 30th and another made on the 1st are tracked as two separate months' clears even when both land in the same displayed week, and both are shown there correctly.",
                "Once checked, Black Mage now only appears in the exact week(s) it was actually cleared (no more placeholder icon sitting in every week), and looks and behaves exactly like any other boss there — left-click cycles difficulty, clicking the party-size number edits it, right-click removes it.",
                "Black Mage's monthly Crystal Meso total on the Statistics dashboard is now computed from each clear's own tagged month instead of inferring the month from the storage week's Thursday, fixing incorrect attribution near month boundaries.",
            ]),
            ("v1.21", "2026-08-04", [
                "The Overview calendar's item-drop cells now wrap extra icons onto a new lane underneath instead of squeezing them all into one row as more items are added to a week.",
                "Hovering a boss in the Boss Listing drag-and-drop panel now shows a tooltip with its crystal meso value for every difficulty tier.",
            ]),
            ("v1.20", "2026-07-26", [
                "The 'Completed this week: X/Y characters' counter on the Overview page now also shows the total Crystal Meso earned so far from the characters already marked Done this week.",
                "Meso-excluded (greyed) characters no longer count toward the main 'Completed this week' line — they now get their own 'CW Completed this week: X/Y' line underneath, with its own Meso total, shown only when at least one character is meso-excluded.",
                "Fixed a bug where toggling a character's meso-exclusion twice in the same week (grey it, then un-grey it) could leave it stuck reading as excluded, because the exclusion history lookup picked the first same-week entry instead of the most recent one.",
                "Added a 'Target' field to each Item Results upgrade row, to the right of Result — freed up the space for it by shrinking the oversized Upgrade Type text box.",
                "Tasks and Item Results now record the exact time (not just the date) an entry was Opened/Closed, so 'Sort by Date' orders same-day entries by earliest-to-latest instead of leaving them in an arbitrary order.",
                "Fixed the Tasks and Item Results rows so the Opened/Closed label no longer sits behind a large stretched gap — the extra space is now reserved right before the action buttons instead.",
                "Added an optional 🔗 link button on every character task row: link a task to one of that same character's Item Results upgrades (Item → Upgrade Type), and checking either one off now completes both. Linking is entirely optional, always same-character only, and can be toggled off any time. General (character-less) tasks don't get a link button, since there's no owning character to restrict the link to.",
                "The linked-item text shown on a linked task row is now clickable — it jumps straight to the global Item Results page (Uncompleted or Completed, whichever the upgrade currently belongs to), instead of the character's Boss Schedule view.",
                "Added Jupiter as a trackable boss (Normal difficulty, Grindstone of Faith drop).",
            ]),
            ("v1.19", "2026-07-10", [
                "Hovering a character card now shows the real projected Crystal Meso for the current week based on the bosses already checked off, instead of showing 0 until 'Mark Done' is clicked.",
                "The 'Crystal Meso' row in a character's Boss Schedule view now shows an italic 'Estimated: X' figure for the current/future week until it's marked Done, then switches to the locked-in total.",
                "Tasks and Item Results now record an 'Opened' date when created and a 'Closed' date when checked off (cleared again if unchecked), shown as a small label on each row — in both the per-character tabs and the global Tasks / Item Results pages.",
                "Any existing Tasks or Item Results that didn't have dates yet were backfilled with today's date.",
                "Fixed a bug in the Item Results tab where clicking anywhere on the item description text (not just the checkbox) would toggle it complete.",
            ]),
            ("v1.18", "2026-07-10", [
                "Added a 'Complete All' button on the Overview page that marks every character as done for the current week in one click, plus a live 'Completed this week: X/Y characters' counter under the header.",
                "Each week column in a character's Boss Schedule view now has its own 'Mark Done' button, so past weeks that were missed can be marked (or unmarked) complete — this was previously locked to only the real current week.",
                "Future weeks can no longer be marked complete — the per-week 'Mark Done' button is disabled (with a tooltip) for any week after the current one.",
                "Added a new 'Item Results' tab (both a global page next to Tasks, and a per-character tab next to Tasks in the Boss Schedule view) for logging item upgrade attempts with Item, Upgrade Type, Amount, and Result fields.",
                "Item Results entries have a checkbox and are split into 'Uncompleted' / 'Completed' tabs, mirroring the Tasks feature.",
                "The Amount field in the Item Results dialog is a directly-editable number box plus a separate 'Add' button to bump it, instead of spinner arrows.",
                "Life Boss Ring Box now has a special 2-state left-click toggle in the Weekly Tracker calendar: plain icon, or the icon stamped with a small Grindstone of Life badge to mark it as converted — instead of the normal 3-state cycle.",
                "Added Grindstone of Life stats: a 'Ring Boxes / Grindstones / % Converted' label on each character's Boss Totals tab, and a matching table (per character plus an all-characters Total row) at the bottom of the Statistics → Boss Clears tab.",
            ]),
            ("v1.17", "2026-07-01", [
                "The 'Boss Listing' drag-and-drop panel (used to drag bosses onto the calendar) is now split into two groups instead of one long list.",
                "Bosses worth 200m or more crystal meso (at their highest difficulty) are listed first; bosses worth less than 200m are grouped under a 'Lower Price Bosses' divider below.",
            ]),
            ("v1.16", "2026-06-29", [
                "Meso and crystal counts for the current week (and any future week) are now 0 until the character is marked as Done.",
                "Clicking 'Mark Done' on a character card locks in their meso and crystal totals for that week in all statistics views.",
                "Past weeks are unaffected — they continue to count all configured bosses as before.",
            ]),
            ("v1.15", "2026-06-29", [
                "Crystal counts in all statistics tables now exclude meso-excluded (greyed) characters, matching meso totals.",
                "Exclusion is now tracked per-week: when you grey a character, only weeks from that point forward stop counting. Ungreying later resumes counting from that week onward.",
                "All stat sections (weekly meso, weekly crystals, monthly meso, monthly crystals, Black Mage monthly) respect the per-week exclusion history.",
            ]),
            ("v1.14", "2026-06-29", [
                "Black Mage is no longer counted in the Weekly Crystal Meso totals (weekly chart, table, hover preview, and boss schedule meso row).",
                "Added a new 'Monthly Black Mage Meso' section at the bottom of the Meso Income statistics tab.",
                "The new section shows a bar chart and table of Black Mage crystal meso grouped by month (last 6 months), across all non-excluded characters.",
            ]),
            ("v1.13", "2026-06-28", [
                "Character cards in the Overview now only show the task summary label when there are open (undone) tasks.",
                "If all tasks are completed or a character has no tasks, the label is hidden entirely.",
            ]),
            ("v1.12", "2026-06-28", [
                "Marking a character as done now pushes them to the bottom of the Overview, while undone characters stay on top.",
                "Within each group (undone / done), the original character order is preserved.",
                "Unmarking a character instantly moves them back up to the undone section.",
            ]),
            ("v1.11", "2026-06-25", [
                "Tasks now support editing: a ✎ button on each row opens a pre-filled text dialog.",
                "Tasks can be reordered with ▲ / ▼ arrow buttons on each row (moves within the same To Do or Completed group).",
                "Tasks can also be reordered by dragging the ⠿ handle up or down with the mouse.",
                "Added a General Tasks section at the top of the global Tasks page. These tasks are not tied to any character and support the same add, check, edit, move, and drag functionality.",
                "Clicking a character's name/header in the global Tasks page navigates directly to that character's boss schedule view.",
                "Character task rows in the global Tasks page now also have ▲ ▼ ✎ × buttons, matching the individual character tab.",
                "The General Tasks section now hides automatically in each tab when that tab has no general tasks to show.",
                "Fixed a bug where tasks would drift further down the page each time a task was checked or unchecked.",
                "Added a '+ Add Character Task' button in the global Tasks page that lets you pick a character from a dropdown and add a task to them.",
                "Each character's task section in the global Tasks page now has an inline '+ Add Task' link at the bottom for quick task entry without leaving the page.",
            ]),
            ("v1.10", "2026-06-25", [
                "Hovering over a dropped item in the Weekly Tracker now shows which boss it came from.",
                "The tooltip displays the boss name and difficulty (e.g. 'From: Zakum (Hard)') when a source was recorded.",
                "Items dropped from a single matching boss are attributed automatically; multi-boss items show the boss chosen at drop time.",
            ]),
            ("v1.9", "2026-06-25", [
                "Fixed crash that occurred when adding a task or entering a character's boss schedule view with existing tasks.",
                "Per-character Tasks tab now has two sub-tabs: 'To Do' (uncompleted) and 'Completed'. Checking a task moves it to Completed instantly; unchecking moves it back.",
                "The global Tasks page (top nav) also uses To Do / Completed tabs. Each tab groups tasks by character and shows a placeholder when empty.",
                "Renamed the top-nav tab from 'All Tasks' to 'Tasks' and moved it before 'Version History' in the navigation bar.",
                "Delete (×) button appears inline on each task row in both the character view and the global Tasks page.",
            ]),
            ("v1.8", "2026-06-25", [
                "Added per-character task lists. Inside a character's boss schedule view, a new 'Tasks' tab appears after 'Drop Rates'.",
                "Click '+ Add Task' to create a task for that character. Check the checkbox to mark it done; uncheck to undo.",
                "Click 'Delete Selected' to remove the highlighted task.",
                "Task completion progress (e.g. '2/5 tasks') is shown on each character card in the Weekly Tracker overview.",
                "Added a new global 'All Tasks' tab in the top navigation bar. It lists every character's tasks with checkboxes — tasks can be toggled from here without entering a character's schedule view.",
                "The character header in All Tasks turns green when all tasks for that character are complete.",
                "Task data is saved across sessions and cleaned up automatically when a character is deleted.",
            ]),
            ("v1.7", "2026-06-25", [
                "Added per-character weekly completion mark ('Mark Done' / '✓ Done' button) on each character card in the Overview.",
                "Click 'Mark Done' to mark a character as completed for the current week — the button turns green and shows '✓ Done'.",
                "Click again to unmark. Marks are week-keyed and automatically disappear at the start of each new week.",
                "Completion marks are saved across sessions and restored on app launch.",
            ]),
            ("v1.6", "2026-06-21", [
                "Right-click a character card in the Overview to toggle meso exclusion.",
                "Excluded characters are greyed out and labelled 'meso excluded' on their card.",
                "Their meso income is removed from all Statistics totals (weekly and monthly meso charts and tables).",
                "Boss clears, crystal counts, item drops, and drop rates still count normally for excluded characters.",
                "Toggle is persistent across sessions. Right-click again to re-include the character.",
                "Drag-and-drop character reordering: hold and drag a character card onto another to move it to that position.",
            ]),
            ("v1.5", "2026-06-21", [
                "Boss Totals and Drop Rates tables in the character boss schedule view now expand to fill available vertical space instead of being capped at a fixed height.",
                "Boss Clears and Item Drop Rates tables in the Statistics dashboard no longer have fixed heights — they grow to show all rows, with the tab's scroll area handling overflow.",
            ]),
            ("v1.4", "2026-06-21", [
                "Added sortable column headers to the Boss Clears and Drop Rates tables in the Statistics dashboard.",
                "Added sortable column headers to the Boss Totals and Drop Rates tabs inside the character boss schedule view.",
                "Boss column sorts alphabetically (A→Z / Z→A). Clears and Rate % columns sort numerically (high→low / low→high). Click a header once to sort ascending, again to sort descending.",
                "Added category filter checkboxes (Pitched, Dawn, Brilliant, Others) above the Item Drop Rates table in both the Statistics dashboard and the character boss schedule view.",
                "Unchecking a category instantly hides those items from the drop rates table; filter state persists across data refreshes.",
            ]),
            ("v1.3", "2026-06-20", [
                "Fixed Eternal Armor Box (Kalos) and Eternal Armor Box (Limbo) not triggering the boss picker dialog when dragged onto a week cell.",
                "Root cause: asset filenames were missing a space before the parenthesis (e.g. 'Eternal Armor Box(kalos).png') causing a mismatch with BOSS_DROPS entries ('Eternal Armor Box (Kalos)'). No boss was ever matched so the dialog was skipped.",
                "Renamed both files in assets/ and dist/assets/ to include the space, aligning them with BOSS_DROPS.",
            ]),
            ("v1.2", "2026-06-18", [
                "Added Version History tab.",
                "Added label font size control (−/+ buttons) in the top bar — adjustable from 8px to 24px, default 11px.",
                "Font size preference is saved and restored between sessions.",
                "Fixed syntax error in Chaos difficulty stylesheet (stray token and typo in 'transparent').",
                "Added Malefic Star boss (Normal / Hard) with placeholder meso values.",
                "Malefic Star Normal drops: Grindstone of Life.",
                "Malefic Star Hard drops: Grindstone of Faith, Eternal Armor Box (Kalos), Life Boss Ring Box, Blissful Nightmare.",
                "Added item category divisions in the Item Inventory panel: Pitched, Dawn, Brilliant, Others.",
                "Updated Limbo Hard drops to include Whisper of the Source.",
            ]),
            ("v1.1", "2025-?-?", [
                "Fixed translucent visual treatment for inherited (rolling rollover) timeline entries.",
                "Rewrote boss state resolution engine as non-recursive chronological timeline scan.",
                "Monthly boss (Black Mage) now correctly inherits only from the most recent monthly week.",
            ]),
            ("v1.0", "2025-?-?", [
                "Initial release.",
                "Weekly boss drop tracker with drag-and-drop item inventory.",
                "Character profiles with rename, delete, and reorder support.",
                "Boss schedule page with difficulty and party size per week.",
                "Statistics dashboard with meso income charts and boss clear history.",
                "Auto-population of boss schedule from previous week on app startup.",
            ]),
        ]

        entry_style = "background-color: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 6px;"

        for ver, rel_date, changes in versions:
            entry = QFrame()
            entry.setStyleSheet(entry_style)
            entry_layout = QVBoxLayout(entry)
            entry_layout.setContentsMargins(16, 12, 16, 14)
            entry_layout.setSpacing(6)

            header_row = QHBoxLayout()
            ver_lbl = QLabel(ver)
            ver_lbl.setStyleSheet("color: #f0c040; font-size: 16px; font-weight: bold; background: transparent; border: none;")
            header_row.addWidget(ver_lbl)
            date_lbl = QLabel(rel_date)
            date_lbl.setStyleSheet("color: #555555; font-size: 12px; background: transparent; border: none;")
            header_row.addWidget(date_lbl)
            header_row.addStretch()
            entry_layout.addLayout(header_row)

            sep = QFrame()
            sep.setFrameShape(QFrame.Shape.HLine)
            sep.setStyleSheet("background-color: #2a2a2a; border: none;")
            sep.setFixedHeight(1)
            entry_layout.addWidget(sep)

            for change in changes:
                lbl = QLabel(f"• {change}")
                lbl.setStyleSheet("color: #cccccc; font-size: 13px; background: transparent; border: none;")
                lbl.setWordWrap(True)
                entry_layout.addWidget(lbl)

            layout.addWidget(entry)

        layout.addStretch()
        scroll.setWidget(content)

        root = QVBoxLayout(page)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(scroll)
        self.view_stack.addWidget(page)

    # ==========================================
    # FIXED PERSISTENT TIMELINE EVALUATION ENGINE (NON-RECURSIVE)
    # ==========================================
    def resolve_boss_state_at_week(self, char_id, target_week_str, boss_image_path):
        """(state, inherited) for this boss on this week: the explicit stamp if there is one,
        else the most recent earlier stamp (inherited), else None. Week keys are ISO dates, so
        plain string comparison orders them correctly."""
        _cache_key = (char_id, target_week_str, boss_image_path)
        if _cache_key in self._resolve_cache:
            return self._resolve_cache[_cache_key]
        result = self._resolve_cache[_cache_key] = self._resolve_uncached(char_id, target_week_str, boss_image_path)
        return result

    def _resolve_uncached(self, char_id, target_week_str, boss_image_path):
        for b in self.saved_boss_clears.get((char_id, target_week_str), []):
            if b["path"] == boss_image_path:
                return b, False

        # Monthly bosses (e.g. Black Mage) are marked done once per run, on whichever exact
        # week the user checks it off — they never roll forward into other weeks.
        # Future weeks never inherit either — bosses must be manually added each week.
        fname_key = os.path.splitext(os.path.basename(boss_image_path))[0].lower()
        if fname_key in MONTHLY_BOSSES or target_week_str > self.actual_current_week_key:
            return None, False

        best_wk, best = None, None
        for (c, wk), stored_list in self.saved_boss_clears.items():
            if c != char_id or wk >= target_week_str or (best_wk is not None and wk < best_wk):
                continue
            for b in stored_list:
                if b["path"] == boss_image_path:
                    best_wk, best = wk, b
                    break

        if best is not None and not best.get("is_deleted_marker", False):
            return best, True
        return None, False

    def _today_str(self):
        return datetime.now().strftime("%Y-%m-%d %H:%M")

    def _fmt_dt_short(self, s):
        if not s:
            return s
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(s, fmt)
            except ValueError:
                continue
            return dt.strftime("%b %d, %H:%M") if fmt == "%Y-%m-%d %H:%M" else dt.strftime("%b %d")
        return s

    def _sync_linked_upgrade_from_task(self, task, done):
        """When a task with an optional Item Result link is checked/unchecked, mirror the state onto the linked upgrade."""
        link = task.get("linked")
        if not link:
            return
        upg = self._upgrade_at(link.get("char_id"), link.get("item_idx", -1), link.get("upg_idx", -1))
        if upg is None:
            return
        upg["done"] = done
        upg["closed"] = self._today_str() if done else None

    def _sync_linked_tasks_from_upgrade(self, char_id, item_idx, upg_idx, done):
        """When an Item Result upgrade is checked/unchecked, mirror the state onto any task linked to it."""
        for tasks in list(self.char_tasks.values()) + [self.global_tasks]:
            for task in tasks:
                link = task.get("linked")
                if (link and link.get("char_id") == char_id
                        and link.get("item_idx") == item_idx and link.get("upg_idx") == upg_idx):
                    task["done"] = done
                    task["closed"] = self._today_str() if done else None

    def _clear_or_shift_task_links(self, char_id, item_idx, upg_idx=None):
        """Keep task links valid after an Item Result upgrade (or whole item) is deleted."""
        for tasks in list(self.char_tasks.values()) + [self.global_tasks]:
            for task in tasks:
                link = task.get("linked")
                if not link or link.get("char_id") != char_id:
                    continue
                if upg_idx is None:
                    if link["item_idx"] == item_idx:
                        task["linked"] = None
                    elif link["item_idx"] > item_idx:
                        link["item_idx"] -= 1
                else:
                    if link["item_idx"] != item_idx:
                        continue
                    if link["upg_idx"] == upg_idx:
                        task["linked"] = None
                    elif link["upg_idx"] > upg_idx:
                        link["upg_idx"] -= 1

    def _prompt_pick_item_upgrade_link(self, default_char_id):
        """Item -> Upgrade Type picker within a single (fixed) character's Item Results. Returns
        {"char_id","item_idx","upg_idx"} or None if cancelled. Tasks can only link within their own character."""
        char = next((c for c in self.characters if c["id"] == default_char_id), None)
        if char is None:
            return None
        entries = self.char_item_results.get(char["id"], [])
        if not entries:
            QMessageBox.information(self, "No Item Results", f"{char['name']} has no item results yet.")
            return None
        item_labels = [e.get("item", "") for e in entries]
        item_name, ok = QInputDialog.getItem(self, "Link Task", "Item:", item_labels, 0, False)
        if not ok:
            return None
        item_idx = item_labels.index(item_name)
        upgrades = entries[item_idx].get("upgrades", [])
        if not upgrades:
            QMessageBox.information(self, "No Upgrades", f"{item_name} has no upgrade types yet.")
            return None
        upg_labels = [u.get("upgrade_type") or f"Upgrade {i + 1}" for i, u in enumerate(upgrades)]
        upg_name, ok = QInputDialog.getItem(self, "Link Task", "Upgrade Type:", upg_labels, 0, False)
        if not ok:
            return None
        upg_idx = upg_labels.index(upg_name)
        return {"char_id": char["id"], "item_idx": item_idx, "upg_idx": upg_idx}

    def _sort_indexed(self, indexed_items, mode, name_key, date_key="opened"):
        if mode == "name":
            return sorted(indexed_items, key=lambda p: (p[1].get(name_key) or "").lower())
        if mode == "date":
            return sorted(indexed_items, key=lambda p: p[1].get(date_key) or "")
        return list(indexed_items)

    def _make_sort_combo(self, current_mode, on_change):
        combo = QComboBox()
        combo.addItem("Manual Order", "manual")
        combo.addItem("Sort by Date", "date")
        combo.addItem("Sort by Name", "name")
        combo.setCurrentIndex({"manual": 0, "date": 1, "name": 2}.get(current_mode, 0))
        combo.setStyleSheet(
            "QComboBox { background-color: #2a2a2a; color: white; border: 1px solid #3a3a3a;"
            " border-radius: 4px; padding: 3px 8px; font-size: 11px; }"
            "QComboBox QAbstractItemView { background-color: #2a2a2a; color: white;"
            " selection-background-color: #3a4a5a; }")
        combo.currentIndexChanged.connect(lambda i: on_change(combo.itemData(i)))
        return combo

    def _sync_sort_combo(self, combo, mode):
        if combo is None:
            return
        combo.blockSignals(True)
        combo.setCurrentIndex({"manual": 0, "date": 1, "name": 2}.get(mode, 0))
        combo.blockSignals(False)

    def _set_tasks_sort_mode(self, mode):
        if mode == self.tasks_sort_mode:
            return
        self.tasks_sort_mode = mode
        self._sync_sort_combo(getattr(self, '_char_tasks_sort_combo', None), mode)
        self._sync_sort_combo(getattr(self, '_global_tasks_sort_combo', None), mode)
        self._refresh_char_tasks_tab()
        if hasattr(self, '_all_todo_layout'):
            self.update_all_tasks_page()

    def _set_item_results_sort_mode(self, mode):
        if mode == self.item_results_sort_mode:
            return
        self.item_results_sort_mode = mode
        self._sync_sort_combo(getattr(self, '_char_items_sort_combo', None), mode)
        self._sync_sort_combo(getattr(self, '_global_items_sort_combo', None), mode)
        self._refresh_char_item_results_tab()
        if hasattr(self, '_all_item_results_todo_layout'):
            self.update_item_results_page()

    def _recent_months(self, n=6):
        """(year, month) for the last n calendar months, oldest first, ending with the current one."""
        base = self.actual_current_thursday.year * 12 + self.actual_current_thursday.month - 1
        return [((base - i) // 12, (base - i) % 12 + 1) for i in range(n - 1, -1, -1)]

    def _month_week_keys(self, year, month):
        """Week keys for every Thursday in this month that isn't in the future."""
        first = date(year, month, 1)
        thu = first + timedelta(days=(3 - first.weekday()) % 7)
        keys = []
        while thu.month == month and thu <= self.actual_current_thursday:
            keys.append(thu.strftime("%Y-%m-%d"))
            thu += timedelta(days=7)
        return keys

    def _refresh_meso_history(self):
        if self.selected_char_id is None:
            return
        self.meso_chart.set_data([
            (date(y, m, 1).strftime("%b"), self.calculate_monthly_crystal_meso(self.selected_char_id, y, m))
            for y, m in self._recent_months()
        ])

    def _count_ring_box_stats(self, char_id=None):
        """Returns (ring_boxes_obtained, converted_to_grindstone) for one character, or all if char_id is None."""
        boxes = 0
        grindstones = 0
        for (cid, wkey), items in self.saved_item_drops.items():
            if char_id is not None and cid != char_id:
                continue
            for it in items:
                stem = os.path.splitext(os.path.basename(it["path"]))[0].lower()
                if stem in SPECIAL_ITEM_OVERLAYS:
                    boxes += 1
                    if it.get("converted", False):
                        grindstones += 1
        return boxes, grindstones

    def _tally_boss_clears(self, char_ids):
        """Walk every week from each boss's first stamp through today. Returns
        (boss_counts, boss_items, rates):
          boss_counts[(display, key, diff)] = clears
          boss_items[(display, key, diff)][item_stem] = copies obtained (state 0 only)
          rates[(item_display, "Display (Diff)")] = (weeks_obtained, clears)"""
        boss_counts, boss_items, rates = {}, {}, {}
        for cid in char_ids:
            first_week = {}
            for (c, wkey), boss_list in self.saved_boss_clears.items():
                if c != cid:
                    continue
                for b in boss_list:
                    if wkey < first_week.get(b["path"], "9"):
                        first_week[b["path"]] = wkey
            for path, key, raw in _boss_files():
                start = first_week.get(path)
                if start is None:
                    continue
                cursor = datetime.strptime(start, "%Y-%m-%d").date()
                while cursor <= self.actual_current_thursday:
                    wkey = cursor.strftime("%Y-%m-%d")
                    cursor += timedelta(days=7)
                    state, _ = self.resolve_boss_state_at_week(cid, wkey, path)
                    if not state or state.get("is_deleted_marker", False):
                        continue
                    diff = state.get("difficulty", "Normal")
                    bkey = (raw, key, diff)
                    boss_counts[bkey] = boss_counts.get(bkey, 0) + 1
                    possible = {d.lower(): d for d in BOSS_DROPS.get((key, diff), [])}
                    if not possible:
                        continue
                    this_boss_key = f"{key}|{diff}"
                    obtained = set()
                    for it in self.saved_item_drops.get((cid, wkey), []):
                        s = _item_state(it)
                        if s == 2:
                            continue
                        stem = os.path.splitext(os.path.basename(it["path"]))[0].lower()
                        if stem in possible and it.get("boss_key") in (None, this_boss_key):
                            obtained.add(stem)
                            if s == 0:
                                bi = boss_items.setdefault(bkey, {})
                                bi[stem] = bi.get(stem, 0) + 1
                    label = f"{raw} ({diff})"
                    for stem, display in possible.items():
                        ob, cl = rates.get((display, label), (0, 0))
                        rates[(display, label)] = (ob + (stem in obtained), cl + 1)
        return boss_counts, boss_items, rates

    def _fill_boss_totals_table(self, table, boss_counts, boss_items):
        table.setSortingEnabled(False)
        table.setRowCount(0)
        for (raw_name, key, diff), total in sorted(boss_counts.items(), key=lambda x: -x[1]):
            drops = BOSS_DROPS.get((key, diff), [])
            ic = boss_items.get((raw_name, key, diff), {})
            items_str = ",  ".join(f"{item} ×{ic.get(item.lower(), 0)}" for item in drops) if drops else "—"
            row = table.rowCount()
            table.insertRow(row)
            table.setItem(row, 0, QTableWidgetItem(f"{raw_name} ({diff})"))
            table.setItem(row, 1, _NumItem(total))
            table.setItem(row, 2, QTableWidgetItem(items_str))
        table.setSortingEnabled(True)

    def _fill_drop_rates_table(self, table, rates, cat_cbs):
        table.setSortingEnabled(False)
        table.setRowCount(0)
        for (item_display, boss_label), (obtained, clears) in sorted(rates.items()):
            pct_num = obtained / clears * 100 if clears else -1.0
            row = table.rowCount()
            table.insertRow(row)
            table.setItem(row, 0, QTableWidgetItem(item_display))
            table.setItem(row, 1, QTableWidgetItem(boss_label))
            table.setItem(row, 2, QTableWidgetItem(f"{obtained} / {clears}"))
            table.setItem(row, 3, _NumItem(pct_num, f"{pct_num:.1f}%" if clears else "—"))
        table.setSortingEnabled(True)
        self._apply_drop_filter(table, cat_cbs)

    def _refresh_char_clear_tables(self):
        if self.selected_char_id is None:
            return
        cid = self.selected_char_id
        boxes, grindstones = self._count_ring_box_stats(cid)
        pct = f"{grindstones / boxes * 100:.0f}%" if boxes else "—"
        self.char_grindstone_label.setText(f"Ring Boxes: {boxes}   •   Grindstones: {grindstones} ({pct})")
        boss_counts, boss_items, rates = self._tally_boss_clears([cid])
        self._fill_boss_totals_table(self.boss_totals_table, boss_counts, boss_items)
        self._fill_drop_rates_table(self.drop_rates_table, rates, self.char_drop_cat_cbs)

    def _make_cat_filter_row(self):
        container = QWidget()
        container.setStyleSheet("background: transparent;")
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 2, 0, 4)
        row.setSpacing(14)
        cbs = {}
        for cat, color, _ in ITEM_CATEGORIES:
            cb = QCheckBox(cat)
            cb.setChecked(True)
            cb.setStyleSheet(
                f"QCheckBox {{ color: {color}; font-size: 12px; font-weight: bold; background: transparent; }}"
                "QCheckBox::indicator { width: 14px; height: 14px; }"
            )
            row.addWidget(cb)
            cbs[cat] = cb
        row.addStretch()
        return container, cbs

    def _apply_drop_filter(self, table, cat_cbs):
        visible = {cat for cat, cb in cat_cbs.items() if cb.isChecked()}
        for r in range(table.rowCount()):
            item = table.item(r, 0)
            if item is None:
                continue
            name_lower = item.text().lower()
            cat = "Others"
            for c, _, names in ITEM_CATEGORIES[:-1]:
                if name_lower in names:
                    cat = c
                    break
            table.setRowHidden(r, cat not in visible)

    def handle_clear_all_bosses(self):
        if self.selected_char_id is None:
            return
        reply = QMessageBox.question(
            self, "Clear All Bosses",
            "Are you sure you want to clear all boss clears for this character? This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        cid = self.selected_char_id
        keys_to_del = [k for k in self.saved_boss_clears if k[0] == cid]
        for k in keys_to_del:
            del self.saved_boss_clears[k]
        self.save_data()
        self.update_boss_schedule_calendar()

    def handle_clear_all_items(self):
        reply = QMessageBox.question(
            self, "Clear All Items",
            "Are you sure you want to clear all item drops for all characters? This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.saved_item_drops.clear()
        self.save_data()
        self.update_overview_calendar()

    def _get_monthly_thursday(self, year, month):
        """The Thursday on or before the 1st — the week whose exclusion state governs that month's Black Mage."""
        first = date(year, month, 1)
        return first - timedelta(days=(first.weekday() - 3) % 7)

    def _week_is_locked(self, char_id, week_key):
        """Current/future weeks only count once the character is marked Done; past weeks always count."""
        return week_key < self.actual_current_week_key or f"{char_id}|{week_key}" in self.char_completed_weeks

    def calculate_weekly_crystal_meso(self, char_id, week_key, ignore_completion=False):
        if not ignore_completion and not self._week_is_locked(char_id, week_key):
            return 0
        meso_values = sorted(
            (BOSS_DIFFICULTY_MAP.get(key, {}).get(s["difficulty"], 0) // max(s.get("party_size", 1), 1)
             for _p, key, _r, s, _i in self._active_bosses(char_id, week_key)),
            reverse=True)
        return sum(meso_values[:14])

    def calculate_weekly_crystal_count(self, char_id, week_key):
        if not self._week_is_locked(char_id, week_key):
            return 0
        return min(len(self._active_bosses(char_id, week_key)), 14)

    def calculate_blackmage_monthly_meso(self, char_id, year, month):
        """Sum Black Mage crystal meso for this character's clear(s) tagged to this calendar month.

        Tagged by calendar month rather than by week's Thursday, so a clear made on the
        30th and one made on the 1st — even when both land in the same displayed week —
        are correctly split across their own months instead of being conflated.
        """
        target_month = f"{year:04d}-{month:02d}"
        total = 0
        for (c, wk), stored in self.saved_boss_clears.items():
            if c != char_id or wk > self.actual_current_week_key:
                continue
            for b in stored:
                if (b["path"] == _BM_PATH and not b.get("is_deleted_marker", False)
                        and self._blackmage_entry_month(wk, b) == target_month):
                    meso = BOSS_DIFFICULTY_MAP.get("blackmage", {}).get(b["difficulty"], 0)
                    total += meso // max(b.get("party_size", 1), 1)
        return total

    def calculate_monthly_crystal_meso(self, char_id, year, month):
        """Sum weekly crystal meso (excl. Black Mage) for all Thursdays in this month, plus Black Mage for this month."""
        return (sum(self.calculate_weekly_crystal_meso(char_id, wk) for wk in self._month_week_keys(year, month))
                + self.calculate_blackmage_monthly_meso(char_id, year, month))

    def calculate_monthly_crystal_count(self, char_id, year, month):
        return sum(self.calculate_weekly_crystal_count(char_id, wk) for wk in self._month_week_keys(year, month))

    def _included_chars(self, week_key):
        return [c["id"] for c in self.characters if not self._is_char_excluded_at_week(c["id"], week_key)]

    def update_statistics_charts(self):
        if not self._stats_dirty:
            return
        self._stats_dirty = False
        # ── Meso Income tab ─────────────────────────────────────────────
        weekly_data = []
        self.stats_weekly_table.setRowCount(0)
        for i in range(7, -1, -1):
            thu = self.actual_current_thursday - timedelta(weeks=i)
            wkey = thu.strftime("%Y-%m-%d")
            included = self._included_chars(wkey)
            total = sum(self.calculate_weekly_crystal_meso(cid, wkey) for cid in included)
            crystals = sum(self.calculate_weekly_crystal_count(cid, wkey) for cid in included)
            label = thu.strftime("%b %d")
            weekly_data.append((label, total))
            row = self.stats_weekly_table.rowCount()
            self.stats_weekly_table.insertRow(row)
            self.stats_weekly_table.setItem(row, 0, QTableWidgetItem(label))
            self.stats_weekly_table.setItem(row, 1, QTableWidgetItem(str(crystals)))
            self.stats_weekly_table.setItem(row, 2, QTableWidgetItem(_fmt_meso_short(total)))
        self.stats_weekly_chart.set_data(weekly_data)

        monthly_data, bm_monthly_data = [], []
        self.stats_monthly_table.setRowCount(0)
        self.stats_bm_monthly_table.setRowCount(0)
        for year, month in self._recent_months():
            total = crystals = 0
            for wkey_m in self._month_week_keys(year, month):
                for cid in self._included_chars(wkey_m):
                    total += self.calculate_weekly_crystal_meso(cid, wkey_m)
                    crystals += self.calculate_weekly_crystal_count(cid, wkey_m)
            # Black Mage counts in the monthly total; use the monthly week's Thursday for exclusion check
            bm_wkey = self._get_monthly_thursday(year, month).strftime("%Y-%m-%d")
            bm_total = sum(self.calculate_blackmage_monthly_meso(cid, year, month)
                           for cid in self._included_chars(bm_wkey))
            total += bm_total
            short, long = date(year, month, 1).strftime("%b"), date(year, month, 1).strftime("%b %Y")
            monthly_data.append((short, total))
            bm_monthly_data.append((short, bm_total))
            row = self.stats_monthly_table.rowCount()
            self.stats_monthly_table.insertRow(row)
            self.stats_monthly_table.setItem(row, 0, QTableWidgetItem(long))
            self.stats_monthly_table.setItem(row, 1, QTableWidgetItem(str(crystals)))
            self.stats_monthly_table.setItem(row, 2, QTableWidgetItem(_fmt_meso_short(total)))
            row = self.stats_bm_monthly_table.rowCount()
            self.stats_bm_monthly_table.insertRow(row)
            self.stats_bm_monthly_table.setItem(row, 0, QTableWidgetItem(long))
            self.stats_bm_monthly_table.setItem(row, 1, QTableWidgetItem(_fmt_meso_short(bm_total)))
        self.stats_monthly_chart.set_data(monthly_data)
        self.stats_bm_monthly_chart.set_data(bm_monthly_data)

        # ── Boss Clears tab ─────────────────────────────────────────────
        boss_counts, boss_items, rates = self._tally_boss_clears([c["id"] for c in self.characters])
        self._fill_boss_totals_table(self.stats_boss_totals_table, boss_counts, boss_items)
        self._fill_drop_rates_table(self.stats_drop_rates_table, rates, self.stats_drop_cat_cbs)

        self.stats_grindstone_table.setRowCount(0)
        boxes_total = 0
        grindstone_total = 0
        for char in self.characters:
            char_boxes, char_grindstones = self._count_ring_box_stats(char["id"])
            boxes_total += char_boxes
            grindstone_total += char_grindstones
            char_pct = char_grindstones / char_boxes * 100 if char_boxes else -1.0
            char_pct_str = f"{char_pct:.0f}%" if char_boxes else "—"
            row = self.stats_grindstone_table.rowCount()
            self.stats_grindstone_table.insertRow(row)
            self.stats_grindstone_table.setItem(row, 0, QTableWidgetItem(char["name"]))
            self.stats_grindstone_table.setItem(row, 1, _NumItem(char_boxes))
            self.stats_grindstone_table.setItem(row, 2, _NumItem(char_grindstones))
            self.stats_grindstone_table.setItem(row, 3, _NumItem(char_pct, char_pct_str))
        row = self.stats_grindstone_table.rowCount()
        self.stats_grindstone_table.insertRow(row)
        total_pct = grindstone_total / boxes_total * 100 if boxes_total else -1.0
        total_pct_str = f"{total_pct:.0f}%" if boxes_total else "—"
        total_cells = (
            QTableWidgetItem("Total (All Characters)"),
            _NumItem(boxes_total),
            _NumItem(grindstone_total),
            _NumItem(total_pct, total_pct_str),
        )
        for col, cell in enumerate(total_cells):
            cell.setForeground(QColor("#66ccff"))
            self.stats_grindstone_table.setItem(row, col, cell)

    def shift_weeks(self, delta):
        self.view_week_offset += delta
        self.refresh_active_view()

    def jump_to_current_week(self):
        self.view_week_offset = 0
        self.inline_calendar_drawer.setVisible(False)
        self.refresh_active_view()

    def refresh_active_view(self):
        if self.view_stack.currentIndex() == 0:
            self.update_overview_calendar()
        elif self.view_stack.currentIndex() == 1:
            self.update_boss_schedule_calendar()

    def return_to_overview(self):
        self.selected_char_id = None
        self.view_stack.setCurrentIndex(0)
        self.update_overview_calendar()

    def enter_character_boss_view(self, char_id):
        # FIXED SWITCH FLOW: Assign character configurations properties before executing drawing steps
        self.selected_char_id = char_id
        char_match = next((c for c in self.characters if c["id"] == char_id), None)
        if char_match:
            self.boss_page_title.setText(f"{char_match['name']} — Boss Clear Plan")
        self.view_stack.setCurrentIndex(1)
        self.update_boss_schedule_calendar()

    def calculate_visible_weeks_data(self):
        weeks = []
        adjusted_thursday = self.base_thursday + timedelta(weeks=self.view_week_offset)
        for i in range(NUM_WEEKS_TO_SHOW):
            start = adjusted_thursday + timedelta(weeks=i)
            end = start + timedelta(days=6)
            key = start.strftime("%Y-%m-%d")
            weeks.append({"key": key, "header": start.strftime("%b %d, %Y"), "sub": f"to {end.strftime('%b %d, %Y')}",
                          "is_current": (key == self.actual_current_week_key)})
        return weeks

    def update_overview_calendar(self):
        self._hover_timer.stop()
        self._boss_hover_preview.hide()
        while self.overview_grid.count():
            w = self.overview_grid.takeAt(0).widget()
            if w: w.deleteLater()

        weeks = self.calculate_visible_weeks_data()
        self.overview_grid.addWidget(QLabel("Character Profile"), 0, 0, Qt.AlignmentFlag.AlignLeft)
        for col, w in enumerate(weeks, start=1):
            self.overview_grid.addWidget(self.create_week_header_widget(w), 0, col, Qt.AlignmentFlag.AlignCenter)

        undone = [c for c in self.characters if f"{c['id']}|{self.actual_current_week_key}" not in self.char_completed_weeks]
        done   = [c for c in self.characters if f"{c['id']}|{self.actual_current_week_key}" in self.char_completed_weeks]
        sorted_chars = undone + done

        if hasattr(self, 'completed_summary_label'):
            done_ids = {c["id"] for c in done}
            included_chars = [c for c in self.characters if not self._is_char_excluded_at_week(c["id"], self.actual_current_week_key)]
            excluded_chars = [c for c in self.characters if self._is_char_excluded_at_week(c["id"], self.actual_current_week_key)]
            done_included = [c for c in included_chars if c["id"] in done_ids]
            done_excluded = [c for c in excluded_chars if c["id"] in done_ids]

            week_meso = sum(self.calculate_weekly_crystal_meso(c["id"], self.actual_current_week_key) for c in done_included)
            bm_week_meso = sum(self.calculate_weekly_blackmage_meso(c["id"], self.actual_current_week_key) for c in included_chars)
            self.completed_summary_label.setText(
                f"Completed this week: {len(done_included)}/{len(included_chars)} characters  •  Meso: {_fmt_meso_short(week_meso + bm_week_meso)}")

            week_crystal_count = sum(self.calculate_weekly_crystal_count(c["id"], self.actual_current_week_key) for c in done_included)
            bm_week_count = sum(len(self._blackmage_entries_for_week(c["id"], self.actual_current_week_key)) for c in included_chars)
            self.crystals_sold_label.setText(
                f"Crystals sold this week: {week_crystal_count + bm_week_count}")

            if excluded_chars:
                excluded_meso = sum(self.calculate_weekly_crystal_meso(c["id"], self.actual_current_week_key) for c in done_excluded)
                self.completed_summary_excluded_label.setText(
                    f"CW Completed this week: {len(done_excluded)}/{len(excluded_chars)} characters  •  Meso: {_fmt_meso_short(excluded_meso)}")
                self.completed_summary_excluded_label.setVisible(True)
            else:
                self.completed_summary_excluded_label.setVisible(False)

        bm_current_month = datetime.now().strftime("%Y-%m")
        for row, char in enumerate(sorted_chars, start=1):
            is_completed = f"{char['id']}|{self.actual_current_week_key}" in self.char_completed_weeks
            tasks = self.char_tasks.get(char["id"], [])
            total_t = len(tasks)
            done_t = sum(1 for t in tasks if t["done"])
            open_t = total_t - done_t
            task_summary = f"Tasks: {done_t}/{total_t}" if open_t > 0 else None
            _, bm_entry = self._find_blackmage_entry_for_month(char["id"], bm_current_month)
            bm_done = bm_entry is not None
            bm_diff = bm_entry["difficulty"] if bm_entry else None
            self.overview_grid.addWidget(CharacterProfileCard(
                char, self.enter_character_boss_view, self.delete_character, self.rename_character,
                self.move_character_up, self.move_character_down, hover_callback=self.show_boss_hover_preview,
                toggle_meso_cb=self.toggle_meso_exclude, reorder_cb=self.reorder_character_to,
                is_completed=is_completed, complete_cb=self.toggle_char_complete, task_summary=task_summary,
                blackmage_done=bm_done, blackmage_difficulty=bm_diff,
                blackmage_click_cb=(lambda cid=char["id"]: self.toggle_blackmage_week(cid, self.actual_current_week_key)),
                blackmage_edit_cb=(lambda cid=char["id"]: self.edit_blackmage_month(cid)),
            ), row, 0)
            for col, w in enumerate(weeks, start=1):
                cell = DynamicCalendarCell(char["id"], w["key"], w["is_current"], self.drop_loot_callback,
                                           self.toggle_loot_greyout, self.delete_loot_callback,
                                           wrap_cols=4, min_size=(140, 95))
                for idx, item in enumerate(self.saved_item_drops.get((char["id"], w["key"]), [])):
                    cell.add_icon(idx, item["path"], _item_state(item), boss_key=item.get("boss_key"), is_converted=item.get("converted", False))
                self.overview_grid.addWidget(cell, row, col)

        self.overview_grid.setColumnStretch(0, 0)
        for col in range(1, len(weeks) + 1):
            self.overview_grid.setColumnStretch(col, 1)

    def update_boss_schedule_calendar(self):
        while self.boss_grid.count():
            w = self.boss_grid.takeAt(0).widget()
            if w: w.deleteLater()

        if self.selected_char_id is None: return
        weeks = self.calculate_visible_weeks_data()
        self.boss_grid.addWidget(QLabel("Tracking Metric"), 0, 0, Qt.AlignmentFlag.AlignLeft)
        for col, w in enumerate(weeks, start=1):
            self.boss_grid.addWidget(self.create_week_header_widget(w), 0, col, Qt.AlignmentFlag.AlignCenter)

        char_match = next((c for c in self.characters if c["id"] == self.selected_char_id), None)
        self.boss_grid.addWidget(QLabel(f"➔ {char_match['name']}\nBoss Runs"), 1, 0)

        boss_count_by_week = {}
        for col, w in enumerate(weeks, start=1):
            cell = DynamicCalendarCell(char_match["id"], w["key"], w["is_current"], self.drop_boss_callback,
                                       self.toggle_boss_difficulty, self.delete_boss_callback,
                                       party_click_cb=self.handle_party_size_click, wrap_cols=4)

            active = self._active_bosses(char_match["id"], w["key"])
            boss_count_by_week[w["key"]] = len(active)
            for idx, (path, _k, _r, state, is_inherited) in enumerate(active):
                cell.add_icon(idx, path, False, state["difficulty"], state.get("party_size", 1), is_inherited)

            # Black Mage is rendered separately (not through the generic single-entry resolver)
            # since the same week can legitimately hold two clears — one for each of two
            # different calendar months — near a month boundary.
            for bm_idx, bm_entry in enumerate(self._blackmage_entries_for_week(char_match["id"], w["key"])):
                bm_l_cb = lambda cid=char_match["id"], wk=w["key"], i=bm_idx: self.toggle_blackmage_entry_difficulty(cid, wk, i)
                bm_r_cb = lambda cid=char_match["id"], wk=w["key"], i=bm_idx: self.delete_blackmage_entry(cid, wk, i)
                bm_p_cb = lambda cid=char_match["id"], wk=w["key"], i=bm_idx: self.handle_blackmage_entry_party_click(cid, wk, i)
                bm_icon = ClickableCellIcon(bm_idx, bm_entry["path"], False, bm_entry["difficulty"],
                                            bm_entry.get("party_size", 1), False, bm_l_cb, bm_r_cb, bm_p_cb)
                cell.add_custom_widget(bm_icon)

            self.boss_grid.addWidget(cell, 1, col)

        meso_row_lbl = QLabel("Crystal\nMeso")
        meso_row_lbl.setStyleSheet("color: #f0c040; font-size: 10px; font-weight: bold;")
        self.boss_grid.addWidget(meso_row_lbl, 2, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        for col, w in enumerate(weeks, start=1):
            wm = self.calculate_weekly_crystal_meso(self.selected_char_id, w["key"], ignore_completion=True)
            if self._week_is_locked(self.selected_char_id, w["key"]):
                wm_lbl = QLabel(_fmt_meso_short(wm))
                wm_lbl.setStyleSheet("color: #f0c040; font-size: 12px; font-weight: bold; padding: 4px;")
            else:
                wm_lbl = QLabel(f"Estimated:\n{_fmt_meso_short(wm)}")
                wm_lbl.setStyleSheet("color: #a08030; font-size: 11px; font-style: italic; font-weight: bold; padding: 4px;")
            wm_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.boss_grid.addWidget(wm_lbl, 2, col)

        count_row_lbl = QLabel("Bosses\n/14")
        count_row_lbl.setStyleSheet("color: #aaaaaa; font-size: 10px; font-weight: bold;")
        self.boss_grid.addWidget(count_row_lbl, 3, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        for col, w in enumerate(weeks, start=1):
            boss_count = boss_count_by_week[w["key"]]
            color = "#2ecc71" if boss_count <= 14 else "#ff3333"
            count_lbl = QLabel(f"{boss_count}/14")
            count_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            count_lbl.setStyleSheet(f"color: {color}; font-size: 12px; font-weight: bold; padding: 4px;")
            self.boss_grid.addWidget(count_lbl, 3, col)

        complete_row_lbl = QLabel("Weekly\nComplete")
        complete_row_lbl.setStyleSheet("color: #aaaaaa; font-size: 10px; font-weight: bold;")
        self.boss_grid.addWidget(complete_row_lbl, 4, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        for col, w in enumerate(weeks, start=1):
            is_done = f"{self.selected_char_id}|{w['key']}" in self.char_completed_weeks
            is_future = w["key"] > self.actual_current_week_key
            btn_week_done = QPushButton("✓ Done" if is_done else "Mark Done")
            if is_future:
                btn_week_done.setEnabled(False)
                btn_week_done.setToolTip("Future weeks can't be marked complete yet")
                btn_week_done.setStyleSheet(
                    "QPushButton { background-color: #202020; color: #444444; border-radius: 3px; padding: 3px 8px;"
                    " font-size: 11px; border: 1px solid #2a2a2a; }")
            elif is_done:
                btn_week_done.setStyleSheet(
                    "QPushButton { background-color: #1a5c1a; color: #2ecc71; border-radius: 3px; padding: 3px 8px;"
                    " font-size: 11px; font-weight: bold; border: 1px solid #2ecc71; }"
                    "QPushButton:hover { background-color: #1e7a1e; color: white; }")
            else:
                btn_week_done.setStyleSheet(
                    "QPushButton { background-color: #2a2a2a; color: #666666; border-radius: 3px; padding: 3px 8px;"
                    " font-size: 11px; border: 1px solid #3a3a3a; }"
                    "QPushButton:hover { background-color: #333333; color: #aaaaaa; }")
            btn_week_done.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_week_done.clicked.connect(lambda checked, wk=w["key"]: self.toggle_char_complete_for_week(self.selected_char_id, wk))
            self.boss_grid.addWidget(btn_week_done, 4, col, Qt.AlignmentFlag.AlignCenter)

        self.refresh_bottom_boss_shelf()
        monthly = self.calculate_monthly_crystal_meso(
            self.selected_char_id,
            self.actual_current_thursday.year,
            self.actual_current_thursday.month,
        )
        self.lbl_monthly_meso.setText(_fmt_meso_short(monthly))
        self._refresh_meso_history()
        self._refresh_char_clear_tables()
        self._refresh_char_tasks_tab()
        self._refresh_char_item_results_tab()

    def refresh_bottom_boss_shelf(self):
        while self.boss_shelf_layout.count():
            widget = self.boss_shelf_layout.takeAt(0).widget()
            if widget: widget.deleteLater()

        boss_files = [b for b in _boss_files() if b[1] not in MONTHLY_BOSSES]
        higher_value_files = [b for b in boss_files if _boss_worth(b[1]) >= LOWER_PRICE_THRESHOLD]
        lower_value_files = [b for b in boss_files if _boss_worth(b[1]) < LOWER_PRICE_THRESHOLD]

        row_idx = 0

        def add_boss_widget(boss, row, col):
            path, _key, raw = boss
            self.boss_shelf_layout.addWidget(DraggableAssetItem(raw, path, show_price=True), row, col)

        col_idx = 0
        for boss in higher_value_files:
            add_boss_widget(boss, row_idx, col_idx)
            col_idx += 1
            if col_idx >= 3: col_idx, row_idx = 0, row_idx + 1

        if lower_value_files:
            if col_idx != 0: col_idx, row_idx = 0, row_idx + 1
            sep_lbl = QLabel("Lower Price Bosses (< 200m)")
            sep_lbl.setStyleSheet("color: #888888; font-size: 11px; font-weight: bold; padding: 4px 2px;")
            self.boss_shelf_layout.addWidget(sep_lbl, row_idx, 0, 1, 3)
            row_idx += 1
            col_idx = 0
            for boss in lower_value_files:
                add_boss_widget(boss, row_idx, col_idx)
                col_idx += 1
                if col_idx >= 3: col_idx, row_idx = 0, row_idx + 1

    def _find_matching_bosses_for_item(self, cid, wkey, path):
        """Bosses on the calendar this week whose current difficulty drops this item."""
        item_stem = os.path.splitext(os.path.basename(path))[0].lower()
        matching_bosses = []
        for _p, key, raw, state, _i in self._active_bosses(cid, wkey, include_monthly=True):
            diff = state["difficulty"]
            if item_stem in (d.lower() for d in BOSS_DROPS.get((key, diff), [])):
                matching_bosses.append((key, diff, f"{raw} ({diff})"))
        return matching_bosses

    def _exclude_claimed_bosses(self, cid, wkey, item_stem, candidates):
        """Drop bosses already credited with a copy of this same item this week — each boss only drops one copy per week."""
        used_boss_keys = set()
        for it in self.saved_item_drops.get((cid, wkey), []):
            stem = os.path.splitext(os.path.basename(it["path"]))[0].lower()
            if stem == item_stem and it.get("boss_key"):
                used_boss_keys.add(it["boss_key"])
        return [b for b in candidates if f"{b[0]}|{b[1]}" not in used_boss_keys]

    def _prompt_pick_boss_dialog(self, candidates):
        """Shows the boss picker. Returns a boss_key string, or None if cancelled."""
        dialog = QDialog(self)
        dialog.setWindowTitle("Which boss dropped this item?")
        dialog.setStyleSheet("background-color: #1c1c1c; color: #e0e0e0;")
        dlg_layout = QVBoxLayout(dialog)

        lbl = QLabel("Select the boss that dropped this item:")
        lbl.setStyleSheet("color: #e0e0e0; font-size: 12px; font-weight: bold; padding-bottom: 4px;")
        dlg_layout.addWidget(lbl)

        list_widget = QListWidget()
        list_widget.setStyleSheet(
            "QListWidget { background-color: #2a2a2a; color: white; border: 1px solid #3a3a3a; font-size: 13px; }"
            "QListWidget::item { padding: 6px; }"
            "QListWidget::item:selected { background-color: #e67e22; }")
        for _fk, _d, display in candidates:
            list_widget.addItem(display)
        list_widget.setCurrentRow(0)
        dlg_layout.addWidget(list_widget)

        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btn_box.button(QDialogButtonBox.StandardButton.Ok).setStyleSheet(
            "background-color: #e67e22; color: white; font-weight: bold; padding: 4px 14px; border-radius: 4px;")
        btn_box.button(QDialogButtonBox.StandardButton.Cancel).setStyleSheet(
            "background-color: #3a3a3a; color: white; font-weight: bold; padding: 4px 14px; border-radius: 4px;")
        btn_box.accepted.connect(dialog.accept)
        btn_box.rejected.connect(dialog.reject)
        dlg_layout.addWidget(btn_box)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        row = list_widget.currentRow()
        if 0 <= row < len(candidates):
            fk, d, _ = candidates[row]
            return f"{fk}|{d}"
        return None

    def drop_loot_callback(self, cid, wkey, path):
        item_stem = os.path.splitext(os.path.basename(path))[0].lower()
        all_matching = self._find_matching_bosses_for_item(cid, wkey, path)
        available = self._exclude_claimed_bosses(cid, wkey, item_stem, all_matching)

        boss_key = None
        if len(available) == 1:
            boss_key = f"{available[0][0]}|{available[0][1]}"
        elif len(available) > 1:
            picked = self._prompt_pick_boss_dialog(available)
            if picked is None:
                return
            boss_key = picked

        new_item = {"path": path, "checked": False, "boss_key": boss_key}
        if boss_key is None:
            # No boss available to credit this copy to — either nothing on the calendar
            # drops it, or every matching boss already has a copy this week — so grey it
            # out by default rather than silently counting an item with nothing behind it.
            new_item["state"] = 2
        self.saved_item_drops.setdefault((cid, wkey), []).append(new_item)
        self.save_data()
        self.update_overview_calendar()

    def toggle_loot_greyout(self, cid, wkey, idx):
        items = self.saved_item_drops.get((cid, wkey), [])
        if 0 <= idx < len(items):
            stem = os.path.splitext(os.path.basename(items[idx]["path"]))[0].lower()
            if stem in SPECIAL_ITEM_OVERLAYS:
                items[idx]["converted"] = not items[idx].get("converted", False)
                items[idx]["state"] = 0
                items[idx]["checked"] = False
            else:
                current = _item_state(items[idx])
                new_state = (current + 1) % 3
                items[idx]["state"] = new_state
                items[idx]["checked"] = new_state == 2
            self.save_data()
            self.update_overview_calendar()

    def delete_loot_callback(self, cid, wkey, idx):
        items = self.saved_item_drops.get((cid, wkey), [])
        if 0 <= idx < len(items):
            items.pop(idx)
            self.save_data()
            self.update_overview_calendar()

    # --- BOSS ENGINE CONSTRUCTS ---
    def _upsert_stamp(self, cid, wkey, path, base=None, **updates):
        """Apply `updates` to this week's explicit stamp for `path`, creating it (from `base` over
        the defaults) if there isn't one yet."""
        explicit_list = self.saved_boss_clears.setdefault((cid, wkey), [])
        match = next((b for b in explicit_list if b["path"] == path), None)
        if match is None:
            match = {"path": path, "difficulty": "Normal", "party_size": 1, "is_deleted_marker": False, **(base or {})}
            explicit_list.append(match)
        match.update(updates)

    def _forward_run(self, cid, wkey, path, state):
        """This week plus each following week (through today) where `path` still resolves to the
        same difficulty — the contiguous run a difficulty/party/delete edit applies to."""
        run = [(wkey, state)]
        cursor = datetime.strptime(wkey, "%Y-%m-%d").date() + timedelta(days=7)
        while cursor <= self.actual_current_thursday:
            k = cursor.strftime("%Y-%m-%d")
            ws, _ = self.resolve_boss_state_at_week(cid, k, path)
            if not ws or ws.get("is_deleted_marker", False) or ws["difficulty"] != state["difficulty"]:
                break
            run.append((k, ws))
            cursor += timedelta(days=7)
        return run

    def _edit_scope(self, cid, wkey, path, state):
        """Weeks an edit applies to. An edit to a past week normally bleeds forward through the
        whole inherited run, so ask first; "this week only" pins the next week to its current
        state, which stops the inheritance there."""
        run = self._forward_run(cid, wkey, path, state)
        if wkey >= self.actual_current_week_key or len(run) < 2:
            return run

        box = QMessageBox(self)
        box.setWindowTitle("Apply Change")
        box.setIcon(QMessageBox.Icon.Question)
        box.setText("This is a past week.")
        box.setInformativeText(
            f"This boss carries the same setting through {len(run)} weeks, up to the current week."
            "\n\n"
            "Apply the change to just this week, or to all of them?")
        only_btn = box.addButton("This Week Only", QMessageBox.ButtonRole.AcceptRole)
        all_btn = box.addButton(f"All {len(run)} Weeks", QMessageBox.ButtonRole.AcceptRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setStyleSheet("QLabel { color: #e0e0e0; } QMessageBox { background-color: #1c1c1c; }")
        box.exec()

        clicked = box.clickedButton()
        if clicked is all_btn:
            return run
        if clicked is not only_btn:
            return []
        next_wkey, next_state = run[1]
        self._upsert_stamp(cid, next_wkey, path, dict(next_state))
        return run[:1]

    def drop_boss_callback(self, cid, wkey, path):
        filename_clean = os.path.splitext(os.path.basename(path))[0].lower()
        self._upsert_stamp(cid, wkey, path, difficulty=_default_difficulty(filename_clean),
                           party_size=1, is_deleted_marker=False)

        # Clear cascaded deletion markers in all subsequent weeks so inheritance flows forward
        cursor = datetime.strptime(wkey, "%Y-%m-%d").date() + timedelta(days=7)
        while cursor <= self.actual_current_thursday:
            cursor_wkey = cursor.strftime("%Y-%m-%d")
            cursor_list = self.saved_boss_clears.get((cid, cursor_wkey))
            if cursor_list:
                cursor_list[:] = [b for b in cursor_list if not (b["path"] == path and b.get("is_deleted_marker", False))]
                if not cursor_list:
                    del self.saved_boss_clears[(cid, cursor_wkey)]
            cursor += timedelta(days=7)

        self.save_data()
        self.update_boss_schedule_calendar()

    def _blackmage_entry_month(self, wkey, entry):
        """The calendar month (YYYY-MM) a Black Mage entry belongs to.

        New entries are tagged explicitly with the real month at the moment they were
        checked off, since the boundary week (containing both e.g. the 30th and the 1st)
        can legitimately hold one clear for each of two different months. Legacy entries
        without a tag fall back to their storage week's own Thursday.
        """
        return entry.get("month") or wkey[:7]

    def _last_blackmage_record(self, cid):
        """Most recent past Black Mage clear for this character, across any week."""
        last_record, last_wk = None, ""
        for (c, wk), stored in self.saved_boss_clears.items():
            if c != cid or wk <= last_wk:
                continue
            for b in stored:
                if b["path"] == _BM_PATH and not b.get("is_deleted_marker", False):
                    last_wk, last_record = wk, b
        return last_record

    def _find_blackmage_entry_for_month(self, cid, target_month):
        """Returns (wkey, entry) for this character's clear tagged with target_month, or (None, None)."""
        for (c, wk), stored in self.saved_boss_clears.items():
            if c != cid:
                continue
            for b in stored:
                if b["path"] == _BM_PATH and not b.get("is_deleted_marker", False):
                    if self._blackmage_entry_month(wk, b) == target_month:
                        return wk, b
        return None, None

    def _blackmage_entries_for_week(self, cid, wkey):
        return [b for b in self.saved_boss_clears.get((cid, wkey), [])
                if b["path"] == _BM_PATH and not b.get("is_deleted_marker", False)]

    def calculate_weekly_blackmage_meso(self, char_id, week_key):
        """Black Mage crystal meso from clear(s) actually recorded in this week."""
        total = 0
        for b in self._blackmage_entries_for_week(char_id, week_key):
            difficulty = b["difficulty"]
            party_size = max(b.get("party_size", 1), 1)
            meso = BOSS_DIFFICULTY_MAP.get("blackmage", {}).get(difficulty, 0)
            total += meso // party_size
        return total

    def toggle_blackmage_week(self, cid, wkey):
        """Toggle this real calendar month's Black Mage clear — once per month, wherever it lives.

        Checking it for the first time ever asks for difficulty and party size. Every
        time after that, checking it just reuses whatever was used last time. `wkey` is
        only where a brand-new clear gets recorded — an existing one is found and
        toggled off from wherever it actually is, since that can be a different week
        than "today" if the month hasn't rolled over since it was checked.
        """
        if not os.path.exists(_BM_PATH):
            return
        current_month = datetime.now().strftime("%Y-%m")
        found_wkey, found_entry = self._find_blackmage_entry_for_month(cid, current_month)

        if found_entry is not None:
            explicit_list = self.saved_boss_clears.get((cid, found_wkey), [])
            explicit_list.remove(found_entry)
            if not explicit_list:
                del self.saved_boss_clears[(cid, found_wkey)]
            self.save_data()
            self.update_boss_schedule_calendar()
            self.update_overview_calendar()
            return

        last_record = self._last_blackmage_record(cid)
        if last_record is not None:
            difficulty = last_record["difficulty"]
            party_size = last_record.get("party_size", 1)
        else:
            tiers = list(BOSS_DIFFICULTY_MAP.get("blackmage", {"Hard": 0, "Extreme": 0}).keys())
            difficulty, ok = QInputDialog.getItem(self, "Black Mage Difficulty", "Select the difficulty cleared:",
                                                  tiers, 0, editable=False)
            if not ok:
                return
            party_size, ok2 = QInputDialog.getInt(self, "Black Mage Party Size", "Enter runners amount:",
                                                   value=1, min=1, max=6)
            if not ok2:
                return

        explicit_list = self.saved_boss_clears.setdefault((cid, wkey), [])
        explicit_list.append({"path": _BM_PATH, "difficulty": difficulty, "party_size": party_size,
                              "is_deleted_marker": False, "month": current_month})
        self.save_data()
        self.update_boss_schedule_calendar()
        self.update_overview_calendar()

    def edit_blackmage_month(self, cid):
        """Right-click on the Overview checkmark — edit this real calendar month's difficulty/party size."""
        current_month = datetime.now().strftime("%Y-%m")
        found_wkey, found_entry = self._find_blackmage_entry_for_month(cid, current_month)
        if found_entry is None:
            QMessageBox.information(self, "Not Marked Yet",
                                     "Black Mage hasn't been marked done this month yet — left-click the checkmark first.")
            return

        tiers = list(BOSS_DIFFICULTY_MAP.get("blackmage", {"Hard": 0, "Extreme": 0}).keys())
        current_idx = tiers.index(found_entry["difficulty"]) if found_entry["difficulty"] in tiers else 0
        difficulty, ok = QInputDialog.getItem(self, "Black Mage Difficulty", "Select the difficulty cleared:",
                                              tiers, current_idx, editable=False)
        if not ok:
            return
        party_size, ok2 = QInputDialog.getInt(self, "Black Mage Party Size", "Enter runners amount:",
                                               value=found_entry.get("party_size", 1), min=1, max=6)
        if not ok2:
            return

        found_entry["difficulty"] = difficulty
        found_entry["party_size"] = party_size
        self.save_data()
        self.update_boss_schedule_calendar()
        self.update_overview_calendar()

    def toggle_blackmage_entry_difficulty(self, cid, wkey, idx):
        entries = self._blackmage_entries_for_week(cid, wkey)
        if not (0 <= idx < len(entries)):
            return
        entry = entries[idx]
        tiers = list(BOSS_DIFFICULTY_MAP.get("blackmage", {"Hard": 0, "Extreme": 0}).keys())
        current_i = tiers.index(entry["difficulty"]) if entry["difficulty"] in tiers else 0
        entry["difficulty"] = tiers[(current_i + 1) % len(tiers)]
        self.save_data()
        self.update_boss_schedule_calendar()
        self.update_overview_calendar()

    def handle_blackmage_entry_party_click(self, cid, wkey, idx):
        entries = self._blackmage_entries_for_week(cid, wkey)
        if not (0 <= idx < len(entries)):
            return
        entry = entries[idx]
        new_size, ok = QInputDialog.getInt(self, "Party Setup", "Enter runners amount:",
                                           value=entry.get("party_size", 1), min=1, max=6)
        if not ok:
            return
        entry["party_size"] = new_size
        self.save_data()
        self.update_boss_schedule_calendar()
        self.update_overview_calendar()

    def delete_blackmage_entry(self, cid, wkey, idx):
        entries = self._blackmage_entries_for_week(cid, wkey)
        if not (0 <= idx < len(entries)):
            return
        entry = entries[idx]
        explicit_list = self.saved_boss_clears.get((cid, wkey), [])
        explicit_list.remove(entry)
        if not explicit_list:
            del self.saved_boss_clears[(cid, wkey)]
        self.save_data()
        self.update_boss_schedule_calendar()
        self.update_overview_calendar()

    def _clicked_boss(self, cid, wkey, idx):
        """(path, key, state) for the idx-th visible (non-monthly) boss icon in a week cell, or None."""
        active = self._active_bosses(cid, wkey)
        if not (0 <= idx < len(active)):
            return None
        path, key, _raw, state, _inh = active[idx]
        return path, key, state

    def toggle_boss_difficulty(self, cid, wkey, idx):
        hit = self._clicked_boss(cid, wkey, idx)
        if hit is None:
            return
        target_path, key, current_state = hit
        allowed_tiers = list(BOSS_DIFFICULTY_MAP.get(key, {"Normal": 0, "Hard": 0}).keys())
        new_difficulty = allowed_tiers[(allowed_tiers.index(current_state["difficulty"]) + 1) % len(allowed_tiers)]

        for apply_wkey, ws in self._edit_scope(cid, wkey, target_path, current_state):
            self._upsert_stamp(cid, apply_wkey, target_path, {"party_size": ws.get("party_size", 1)},
                               difficulty=new_difficulty, is_deleted_marker=False)
        self.save_data()
        self.update_boss_schedule_calendar()

    def handle_party_size_click(self, cid, wkey, idx):
        hit = self._clicked_boss(cid, wkey, idx)
        if hit is None:
            return
        target_path, key, current_state = hit
        max_allowed = 3 if key in ("limbo", "baldrix") else 6
        new_size, ok = QInputDialog.getInt(self, "Party Setup", "Enter runners amount:",
                                           value=current_state.get("party_size", 1), min=1, max=max_allowed)
        if not ok:
            return

        for apply_wkey, ws in self._edit_scope(cid, wkey, target_path, current_state):
            self._upsert_stamp(cid, apply_wkey, target_path, {"difficulty": ws.get("difficulty", "Normal")},
                               party_size=new_size, is_deleted_marker=False)
        self.save_data()
        self.update_boss_schedule_calendar()

    def delete_boss_callback(self, cid, wkey, idx):
        hit = self._clicked_boss(cid, wkey, idx)
        if hit is None:
            return
        target_path, _key, clicked_state = hit
        for apply_wkey, _ws in self._edit_scope(cid, wkey, target_path, clicked_state):
            self._upsert_stamp(cid, apply_wkey, target_path, is_deleted_marker=True)
        self.save_data()
        self.update_boss_schedule_calendar()

    def handle_presets_dialog(self):
        if self.selected_char_id is None:
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Boss Presets")
        dialog.setMinimumWidth(480)
        dialog.setMinimumHeight(360)
        dialog.setStyleSheet("background-color: #1c1c1c; color: #e0e0e0;")

        layout = QVBoxLayout(dialog)
        layout.setSpacing(10)

        lbl = QLabel("Saved Presets")
        lbl.setStyleSheet("color: #e67e22; font-size: 13px; font-weight: bold;")
        layout.addWidget(lbl)

        preset_list = QListWidget()
        preset_list.setStyleSheet(
            "QListWidget { background-color: #2a2a2a; color: white; border: 1px solid #3a3a3a; font-size: 12px; }"
            "QListWidget::item:selected { background-color: #6a3a8a; }")
        for p in self.boss_presets:
            preset_list.addItem(p["name"])
        layout.addWidget(preset_list)

        detail_lbl = QLabel("")
        detail_lbl.setStyleSheet("color: #aaaaaa; font-size: 11px;")
        detail_lbl.setWordWrap(True)
        layout.addWidget(detail_lbl)

        def on_selected():
            row = preset_list.currentRow()
            if 0 <= row < len(self.boss_presets):
                parts = [
                    f"{os.path.splitext(os.path.basename(b['path']))[0]} ({b['difficulty']})"
                    for b in self.boss_presets[row]["bosses"]
                ]
                detail_lbl.setText("  •  ".join(parts))
            else:
                detail_lbl.setText("")

        preset_list.currentRowChanged.connect(lambda _: on_selected())

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        btn_save = QPushButton("Save Current Week as Preset")
        btn_save.setStyleSheet(
            "QPushButton { background-color: #27ae60; color: white; font-weight: bold; padding: 5px 10px; border-radius: 4px; }"
            "QPushButton:hover { background-color: #1e8449; }")
        btn_row.addWidget(btn_save)

        btn_apply = QPushButton("Apply to Week…")
        btn_apply.setStyleSheet(
            "QPushButton { background-color: #2980b9; color: white; font-weight: bold; padding: 5px 10px; border-radius: 4px; }"
            "QPushButton:hover { background-color: #1f6391; }")
        btn_row.addWidget(btn_apply)

        btn_rename = QPushButton("Rename")
        btn_rename.setStyleSheet(
            "QPushButton { background-color: #1a3a5a; color: #66aaff; font-weight: bold; padding: 5px 10px; border-radius: 4px; }"
            "QPushButton:hover { background-color: #1f5080; color: white; }")
        btn_row.addWidget(btn_rename)

        btn_edit = QPushButton("Edit Bosses")
        btn_edit.setStyleSheet(
            "QPushButton { background-color: #3a2a5a; color: #aa88ff; font-weight: bold; padding: 5px 10px; border-radius: 4px; }"
            "QPushButton:hover { background-color: #4a3a6a; color: white; }")
        btn_row.addWidget(btn_edit)

        btn_dup = QPushButton("Duplicate")
        btn_dup.setStyleSheet(
            "QPushButton { background-color: #2a3a2a; color: #88cc88; font-weight: bold; padding: 5px 10px; border-radius: 4px; }"
            "QPushButton:hover { background-color: #3a4a3a; color: white; }")
        btn_row.addWidget(btn_dup)

        btn_del = QPushButton("Delete")
        btn_del.setStyleSheet(
            "QPushButton { background-color: #7b2222; color: white; font-weight: bold; padding: 5px 10px; border-radius: 4px; }"
            "QPushButton:hover { background-color: #a02828; }")
        btn_row.addWidget(btn_del)

        layout.addLayout(btn_row)

        def do_rename():
            row = preset_list.currentRow()
            if not (0 <= row < len(self.boss_presets)):
                QMessageBox.warning(dialog, "No Preset Selected", "Select a preset first.")
                return
            old_name = self.boss_presets[row]["name"]
            new_name, ok = QInputDialog.getText(dialog, "Rename Preset", "New name:", text=old_name)
            if not ok or not new_name.strip():
                return
            self.boss_presets[row]["name"] = new_name.strip()
            self.save_data()
            preset_list.item(row).setText(new_name.strip())

        def do_edit_bosses():
            row = preset_list.currentRow()
            if not (0 <= row < len(self.boss_presets)):
                QMessageBox.warning(dialog, "No Preset Selected", "Select a preset first.")
                return
            preset = self.boss_presets[row]

            edit_dlg = QDialog(dialog)
            edit_dlg.setWindowTitle(f"Edit Bosses — {preset['name']}")
            edit_dlg.setMinimumWidth(540)
            edit_dlg.setMinimumHeight(500)
            edit_dlg.setStyleSheet("background-color: #1c1c1c; color: #e0e0e0;")
            ed_layout = QVBoxLayout(edit_dlg)
            ed_layout.setSpacing(8)

            hdr = QLabel("Check bosses to include, then pick difficulty and party size.")
            hdr.setStyleSheet("color: #aaaaaa; font-size: 11px;")
            ed_layout.addWidget(hdr)

            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setStyleSheet("background: transparent; border: none;")
            content = QWidget()
            content.setStyleSheet("background: transparent;")
            grid = QGridLayout(content)
            grid.setSpacing(6)
            grid.setContentsMargins(4, 4, 4, 4)

            all_boss_files = [b for b in _boss_files() if b[1] not in MONTHLY_BOSSES]

            preset_by_path = {b["path"]: b for b in preset["bosses"]}
            row_widgets = []

            diff_colors = {
                "Extreme": "#bf55ec", "Chaos": "#ff9900",
                "Hard": "#ff3333", "Easy": "#2ecc71", "Normal": "#a0a0a0",
            }

            combo_style = (
                "QComboBox { background-color: #2a2a2a; color: white; border: 1px solid #3a3a3a;"
                " border-radius: 3px; padding: 2px 6px; font-size: 11px; }"
                "QComboBox QAbstractItemView { background-color: #2a2a2a; color: white; }"
            )
            spin_style = (
                "QSpinBox { background-color: #2a2a2a; color: white; border: 1px solid #3a3a3a;"
                " border-radius: 3px; padding: 2px 4px; font-size: 11px; }"
            )

            for i, (fpath, boss_key, boss_name) in enumerate(all_boss_files):
                in_preset = fpath in preset_by_path
                existing = preset_by_path.get(fpath, {})

                cb = QCheckBox()
                cb.setChecked(in_preset)
                cb.setStyleSheet("QCheckBox { color: white; }")

                img_lbl = QLabel()
                img_lbl.setPixmap(_scaled_pixmap(fpath, 28))
                img_lbl.setFixedSize(32, 32)

                name_lbl = QLabel(boss_name)
                name_lbl.setStyleSheet("color: #e0e0e0; font-size: 12px;")
                name_lbl.setMinimumWidth(140)

                diff_combo = QComboBox()
                diff_combo.setStyleSheet(combo_style)
                diffs = list(BOSS_DIFFICULTY_MAP.get(boss_key, {"Normal": 0}).keys())
                if not diffs:
                    diffs = ["Normal"]
                diff_combo.addItems(diffs)
                cur_diff = existing.get("difficulty", _default_difficulty(boss_key))
                if cur_diff in diffs:
                    diff_combo.setCurrentText(cur_diff)
                diff_combo.setEnabled(in_preset)

                party_spin = QSpinBox()
                party_spin.setRange(1, 6)
                party_spin.setValue(existing.get("party_size", 1))
                party_spin.setStyleSheet(spin_style)
                party_spin.setEnabled(in_preset)
                party_spin.setFixedWidth(52)

                def _toggle(state, dc=diff_combo, ps=party_spin):
                    dc.setEnabled(bool(state))
                    ps.setEnabled(bool(state))
                cb.stateChanged.connect(_toggle)

                grid.addWidget(cb, i, 0)
                grid.addWidget(img_lbl, i, 1)
                grid.addWidget(name_lbl, i, 2)
                grid.addWidget(diff_combo, i, 3)
                grid.addWidget(QLabel("×"), i, 4)
                grid.addWidget(party_spin, i, 5)

                row_widgets.append((fpath, cb, diff_combo, party_spin))

            scroll.setWidget(content)
            ed_layout.addWidget(scroll)

            ed_btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
            ed_btns.button(QDialogButtonBox.StandardButton.Ok).setStyleSheet(
                "background-color: #6a3a8a; color: white; font-weight: bold; padding: 4px 14px; border-radius: 4px;")
            ed_btns.button(QDialogButtonBox.StandardButton.Cancel).setStyleSheet(
                "background-color: #3a3a3a; color: white; font-weight: bold; padding: 4px 14px; border-radius: 4px;")
            ed_btns.accepted.connect(edit_dlg.accept)
            ed_btns.rejected.connect(edit_dlg.reject)
            ed_layout.addWidget(ed_btns)

            if edit_dlg.exec() != QDialog.DialogCode.Accepted:
                return

            new_bosses = []
            for fpath, cb, diff_combo, party_spin in row_widgets:
                if cb.isChecked():
                    new_bosses.append({
                        "path": fpath,
                        "difficulty": diff_combo.currentText(),
                        "party_size": party_spin.value(),
                    })
            preset["bosses"] = new_bosses
            self.save_data()
            on_selected()

        def do_duplicate():
            row = preset_list.currentRow()
            if not (0 <= row < len(self.boss_presets)):
                QMessageBox.warning(dialog, "No Preset Selected", "Select a preset first.")
                return
            src = self.boss_presets[row]
            new_name, ok = QInputDialog.getText(dialog, "Duplicate Preset", "Name for the copy:",
                                                text=f"Copy of {src['name']}")
            if not ok or not new_name.strip():
                return
            new_preset = {"name": new_name.strip(), "bosses": copy.deepcopy(src["bosses"])}
            self.boss_presets.append(new_preset)
            self.save_data()
            preset_list.addItem(new_name.strip())
            preset_list.setCurrentRow(len(self.boss_presets) - 1)

        def do_save():
            bosses = [{"path": p, "difficulty": s["difficulty"], "party_size": s.get("party_size", 1)}
                      for p, _k, _r, s, _i in self._active_bosses(self.selected_char_id, self.actual_current_week_key)]
            if not bosses:
                QMessageBox.warning(dialog, "No Bosses", "No bosses are set for the current week.")
                return
            name, ok = QInputDialog.getText(dialog, "Preset Name", "Name for this preset:")
            if not ok or not name.strip():
                return
            self.boss_presets.append({"name": name.strip(), "bosses": bosses})
            self.save_data()
            preset_list.addItem(name.strip())

        def do_apply():
            row = preset_list.currentRow()
            if not (0 <= row < len(self.boss_presets)):
                QMessageBox.warning(dialog, "No Preset Selected", "Select a preset first.")
                return
            preset = self.boss_presets[row]
            cid = self.selected_char_id

            cal_dlg = QDialog(dialog)
            cal_dlg.setWindowTitle("Pick a week to apply the preset")
            cal_dlg.setStyleSheet("background-color: #1c1c1c; color: #e0e0e0;")
            cal_layout = QVBoxLayout(cal_dlg)
            cal = QCalendarWidget()
            cal.setGridVisible(True)
            cal.setStyleSheet("""
                QCalendarWidget QWidget { alternate-background-color: #252525; background-color: #1c1c1c; }
                QCalendarWidget QAbstractItemView:enabled { color: #e0e0e0; background-color: #1c1c1c;
                    selection-background-color: #6a3a8a; selection-color: white; }
                QCalendarWidget QMenu { background-color: #1a1a1a; color: white; }
                QCalendarWidget #qt_calendar_navigationbar { background-color: #1a1a1a; padding: 4px; }
                QCalendarWidget QToolButton { color: #e0e0e0; background-color: #2a2a2a; border: 1px solid #3a3a3a; border-radius: 4px; padding: 3px 8px; font-weight: bold; font-size: 13px; }
                QCalendarWidget QToolButton:hover { background-color: #6a3a8a; color: white; }
                QCalendarWidget QSpinBox { color: #e0e0e0; background-color: #2a2a2a; border: 1px solid #3a3a3a; border-radius: 4px; padding: 2px; font-size: 13px; }
            """)
            cal_layout.addWidget(cal)
            cal_btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
            cal_btns.button(QDialogButtonBox.StandardButton.Ok).setStyleSheet(
                "background-color: #6a3a8a; color: white; font-weight: bold; padding: 4px 14px; border-radius: 4px;")
            cal_btns.button(QDialogButtonBox.StandardButton.Cancel).setStyleSheet(
                "background-color: #3a3a3a; color: white; font-weight: bold; padding: 4px 14px; border-radius: 4px;")
            cal_btns.accepted.connect(cal_dlg.accept)
            cal_btns.rejected.connect(cal_dlg.reject)
            cal_layout.addWidget(cal_btns)
            if cal_dlg.exec() != QDialog.DialogCode.Accepted:
                return

            selected_date = cal.selectedDate().toPyDate()
            target_thursday = selected_date - timedelta(days=(selected_date.weekday() - 3) % 7)
            wkey = target_thursday.strftime("%Y-%m-%d")

            for b in preset["bosses"]:
                self._upsert_stamp(cid, wkey, b["path"], difficulty=b["difficulty"],
                                   party_size=b.get("party_size", 1), is_deleted_marker=False)
            self.save_data()
            self.update_boss_schedule_calendar()
            dialog.accept()

        def do_delete():
            row = preset_list.currentRow()
            if not (0 <= row < len(self.boss_presets)):
                return
            self.boss_presets.pop(row)
            self.save_data()
            preset_list.takeItem(row)
            detail_lbl.setText("")

        btn_save.clicked.connect(do_save)
        btn_apply.clicked.connect(do_apply)
        btn_rename.clicked.connect(do_rename)
        btn_edit.clicked.connect(do_edit_bosses)
        btn_dup.clicked.connect(do_duplicate)
        btn_del.clicked.connect(do_delete)

        dialog.exec()

    def handle_add_all_bosses_to_date(self):
        if self.selected_char_id is None:
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Pick a week — all bosses will be added to it")
        dialog.setStyleSheet("background-color: #1c1c1c; color: #e0e0e0;")
        layout = QVBoxLayout(dialog)

        cal = QCalendarWidget()
        cal.setGridVisible(True)
        cal.setStyleSheet("""
            QCalendarWidget QWidget { alternate-background-color: #252525; background-color: #1c1c1c; }
            QCalendarWidget QAbstractItemView:enabled { color: #e0e0e0; background-color: #1c1c1c;
                selection-background-color: #27ae60; selection-color: white; }
            QCalendarWidget QMenu { background-color: #1a1a1a; color: white; }
            QCalendarWidget #qt_calendar_navigationbar { background-color: #1a1a1a; padding: 4px; }
            QCalendarWidget QToolButton { color: #e0e0e0; background-color: #2a2a2a; border: 1px solid #3a3a3a; border-radius: 4px; padding: 3px 8px; font-weight: bold; font-size: 13px; }
            QCalendarWidget QToolButton:hover { background-color: #27ae60; color: white; }
            QCalendarWidget QSpinBox { color: #e0e0e0; background-color: #2a2a2a; border: 1px solid #3a3a3a; border-radius: 4px; padding: 2px; font-size: 13px; }
        """)
        layout.addWidget(cal)

        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btn_box.button(QDialogButtonBox.StandardButton.Ok).setStyleSheet(
            "background-color: #27ae60; color: white; font-weight: bold; padding: 4px 14px; border-radius: 4px;")
        btn_box.button(QDialogButtonBox.StandardButton.Cancel).setStyleSheet(
            "background-color: #3a3a3a; color: white; font-weight: bold; padding: 4px 14px; border-radius: 4px;")
        btn_box.accepted.connect(dialog.accept)
        btn_box.rejected.connect(dialog.reject)
        layout.addWidget(btn_box)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        selected_date = cal.selectedDate().toPyDate()
        target_thursday = selected_date - timedelta(days=(selected_date.weekday() - 3) % 7)
        wkey = target_thursday.strftime("%Y-%m-%d")
        cid = self.selected_char_id

        # Stamp every week from the selected date up to and including the current week
        cursor = target_thursday
        while cursor <= self.actual_current_thursday:
            apply_wkey = cursor.strftime("%Y-%m-%d")
            for path, key, _raw in _boss_files():
                if key in MONTHLY_BOSSES:
                    continue
                self._upsert_stamp(cid, apply_wkey, path, difficulty=_default_difficulty(key),
                                   party_size=1, is_deleted_marker=False)
            cursor += timedelta(days=7)

        self.save_data()
        self.update_boss_schedule_calendar()

    def create_week_header_widget(self, winfo):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        m_lbl = QLabel(winfo["header"])
        m_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        s_lbl = QLabel(winfo["sub"])
        s_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if winfo["is_current"]:
            m_lbl.setStyleSheet("font-weight: bold; color: #ff9900; font-size: 13px;")
            s_lbl.setStyleSheet("color: #ffb366; font-size: 11px; font-weight: bold;")
            tag = QLabel("[ CURRENT ]")
            tag.setStyleSheet("color: #ff9900; font-size: 9px; font-weight: bold;")
            tag.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(m_lbl)
            layout.addWidget(s_lbl)
            layout.addWidget(tag)
        else:
            m_lbl.setStyleSheet("font-weight: bold; color: #b3b3b3; font-size: 13px;")
            s_lbl.setStyleSheet("color: #666666; font-size: 11px;")
            layout.addWidget(m_lbl)
            layout.addWidget(s_lbl)
        return widget

    def add_character_dialog(self):
        name, ok = QInputDialog.getText(self, "New Character", "Character Name:")
        if ok and name:
            self.char_id_counter += 1
            self.characters.append({"id": self.char_id_counter, "name": name})
            self.save_data()
            self.update_overview_calendar()

    def rename_character(self, char_id, current_name):
        new_name, ok = QInputDialog.getText(self, "Rename Character", "New name:", text=current_name)
        if not ok or not new_name.strip() or new_name.strip() == current_name:
            return
        for c in self.characters:
            if c["id"] == char_id:
                c["name"] = new_name.strip()
                break
        self.save_data()
        self.update_overview_calendar()

    def move_character_up(self, char_id):
        idx = next((i for i, c in enumerate(self.characters) if c["id"] == char_id), None)
        if idx is not None and idx > 0:
            self.characters[idx], self.characters[idx - 1] = self.characters[idx - 1], self.characters[idx]
            self.save_data()
            self.update_overview_calendar()

    def move_character_down(self, char_id):
        idx = next((i for i, c in enumerate(self.characters) if c["id"] == char_id), None)
        if idx is not None and idx < len(self.characters) - 1:
            self.characters[idx], self.characters[idx + 1] = self.characters[idx + 1], self.characters[idx]
            self.save_data()
            self.update_overview_calendar()

    def reorder_character_to(self, dragged_id, target_id):
        dragged_idx = next((i for i, c in enumerate(self.characters) if c["id"] == dragged_id), None)
        target_idx = next((i for i, c in enumerate(self.characters) if c["id"] == target_id), None)
        if dragged_idx is None or target_idx is None or dragged_idx == target_idx:
            return
        char = self.characters.pop(dragged_idx)
        if dragged_idx < target_idx:
            target_idx -= 1
        self.characters.insert(target_idx, char)
        self.save_data()
        self.update_overview_calendar()

    def toggle_char_complete(self, char_id):
        key = f"{char_id}|{self.actual_current_week_key}"
        if key in self.char_completed_weeks:
            self.char_completed_weeks.discard(key)
        else:
            self.char_completed_weeks.add(key)
        self.save_data()
        self.update_overview_calendar()

    def complete_all_characters(self):
        for char in self.characters:
            self.char_completed_weeks.add(f"{char['id']}|{self.actual_current_week_key}")
        self.save_data()
        self.update_overview_calendar()

    def toggle_char_complete_for_week(self, char_id, week_key):
        if week_key > self.actual_current_week_key:
            return
        key = f"{char_id}|{week_key}"
        if key in self.char_completed_weeks:
            self.char_completed_weeks.discard(key)
        else:
            self.char_completed_weeks.add(key)
        self.save_data()
        self.update_boss_schedule_calendar()
        self.update_overview_calendar()

    def _is_char_excluded_at_week(self, char_id, week_key):
        """Return whether a character was meso-excluded during a given week, using recorded history."""
        history = self.char_exclusion_history.get(char_id, [])
        if not history:
            char = next((c for c in self.characters if c["id"] == char_id), None)
            return bool(char and char.get("meso_excluded", False))
        relevant = [h for h in history if h["week_key"] <= week_key]
        if not relevant:
            return False
        return relevant[-1]["excluded"]

    def toggle_meso_exclude(self, char_id):
        for c in self.characters:
            if c["id"] == char_id:
                new_state = not c.get("meso_excluded", False)
                c["meso_excluded"] = new_state
                history = self.char_exclusion_history.setdefault(char_id, [])
                history.append({"week_key": self.actual_current_week_key, "excluded": new_state})
                break
        self.save_data()
        self._stats_dirty = True
        self.update_overview_calendar()

    def _refresh_char_tasks_tab(self):
        if not hasattr(self, '_char_todo_layout') or self.selected_char_id is None:
            return
        for layout in (self._char_todo_layout, self._char_done_layout):
            while layout.count():
                item = layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
        tasks = self.char_tasks.get(self.selected_char_id, [])
        done_count = sum(1 for t in tasks if t["done"])
        char = next((c for c in self.characters if c["id"] == self.selected_char_id), None)
        name = char["name"] if char else "Character"
        self.char_tasks_header.setText(f"Tasks for {name}  —  {done_count}/{len(tasks)} done")
        allow_reorder = (self.tasks_sort_mode == "manual")
        undone = self._sort_indexed([(i, t) for i, t in enumerate(tasks) if not t["done"]], self.tasks_sort_mode, "text")
        done = self._sort_indexed([(i, t) for i, t in enumerate(tasks) if t["done"]], self.tasks_sort_mode, "text")
        for idx, task in undone + done:
            is_done = task["done"]
            target_layout = self._char_done_layout if is_done else self._char_todo_layout
            container = self._char_done_container if is_done else self._char_todo_container
            move_fn = lambda ii, dd: self._move_char_task(ii, dd)
            row = self._make_task_row(
                task,
                on_check=lambda state, i=idx: self._on_char_task_check(i, state),
                on_up=lambda _, i=idx: self._move_char_task(i, -1),
                on_down=lambda _, i=idx: self._move_char_task(i, 1),
                on_edit=lambda _, i=idx: self._edit_char_task(i),
                on_delete=lambda _, i=idx: self._delete_char_task(i),
                on_link=lambda _, i=idx: self._link_char_task(i),
                on_drag_press=lambda e, i=idx, mf=move_fn, c=container: self._task_drag_start(e, i, mf, c),
                allow_reorder=allow_reorder,
            )
            target_layout.addWidget(row)

    def _on_char_task_check(self, task_idx, state):
        if self.selected_char_id is None:
            return
        tasks = self.char_tasks.get(self.selected_char_id, [])
        if 0 <= task_idx < len(tasks):
            done = (state != 0)
            task = tasks[task_idx]
            task["done"] = done
            task["closed"] = self._today_str() if done else None
            self._sync_linked_upgrade_from_task(task, done)
            self.save_data()
            self._refresh_char_tasks_tab()

    def _link_char_task(self, task_idx):
        tasks = self.char_tasks.get(self.selected_char_id, [])
        if not (0 <= task_idx < len(tasks)):
            return
        task = tasks[task_idx]
        if task.get("linked"):
            task["linked"] = None
        else:
            link = self._prompt_pick_item_upgrade_link(default_char_id=self.selected_char_id)
            if link is None:
                return
            task["linked"] = link
        self.save_data()
        self._refresh_char_tasks_tab()

    def _add_char_task(self):
        if self.selected_char_id is None:
            return
        text, ok = QInputDialog.getText(self, "Add Task", "Task description:")
        if not ok or not text.strip():
            return
        self.char_tasks.setdefault(self.selected_char_id, []).append(
            {"text": text.strip(), "done": False, "opened": self._today_str(), "closed": None})
        self.save_data()
        self._refresh_char_tasks_tab()

    def _delete_char_task(self, idx):
        if self.selected_char_id is None:
            return
        tasks = self.char_tasks.get(self.selected_char_id, [])
        if 0 <= idx < len(tasks):
            tasks.pop(idx)
            self.save_data()
            self._refresh_char_tasks_tab()

    def _make_task_row(self, task, on_check, on_up, on_down, on_edit, on_delete, on_link=None, on_drag_press=None, allow_reorder=True):
        row_w = QWidget()
        row_w.setStyleSheet("background: transparent;")
        row_l = QHBoxLayout(row_w)
        row_l.setContentsMargins(2, 1, 0, 1)
        row_l.setSpacing(2)
        if on_drag_press is not None and allow_reorder:
            handle = QLabel("⠿")
            handle.setFixedWidth(14)
            handle.setCursor(Qt.CursorShape.SizeVerCursor)
            handle.setStyleSheet("color: #555566; font-size: 13px; background: transparent;")
            handle.mousePressEvent = on_drag_press
            row_l.addWidget(handle)
        cb = QCheckBox(task["text"])
        cb.setChecked(task["done"])
        tc = "#888888" if task["done"] else "#cccccc"
        cb.setStyleSheet(
            f"QCheckBox {{ color: {tc}; font-size: 13px; background: transparent; }}"
            "QCheckBox::indicator { width: 16px; height: 16px; }")
        cb.stateChanged.connect(on_check)
        row_l.addWidget(cb)
        opened = task.get("opened")
        closed = task.get("closed")
        if opened or closed:
            date_text = f"Opened {self._fmt_dt_short(opened)}" if opened else ""
            if task["done"] and closed:
                closed_text = f"Closed {self._fmt_dt_short(closed)}"
                date_text = f"{date_text}  ·  {closed_text}" if date_text else closed_text
            date_lbl = QLabel(date_text)
            date_lbl.setStyleSheet("color: #666666; font-size: 10px; background: transparent;")
            row_l.addWidget(date_lbl)

        link = task.get("linked")
        if link:
            entries = self.char_item_results.get(link.get("char_id"), [])
            item_idx, upg_idx = link.get("item_idx", -1), link.get("upg_idx", -1)
            item_name = entries[item_idx].get("item", "?") if 0 <= item_idx < len(entries) else "?"
            upgrades = entries[item_idx].get("upgrades", []) if 0 <= item_idx < len(entries) else []
            upg_type = upgrades[upg_idx].get("upgrade_type", "?") if 0 <= upg_idx < len(upgrades) else "?"
            link_lbl = QPushButton(f"🔗 {item_name} ({upg_type})")
            link_lbl.setCursor(Qt.CursorShape.PointingHandCursor)
            link_lbl.setToolTip("Go to this Item Result")
            link_lbl.setStyleSheet(
                "QPushButton { color: #5599cc; font-size: 10px; background: transparent; border: none; padding: 0; }"
                "QPushButton:hover { color: #7fb8e0; text-decoration: underline; }")
            link_lbl.clicked.connect(lambda _, ln=link: self._goto_linked_item_result(ln))
            row_l.addWidget(link_lbl)

        row_l.addStretch(1)
        if allow_reorder:
            nav_s = ("QPushButton { background-color: #252535; color: #7777aa; border-radius: 3px;"
                     " font-size: 9px; border: none; }"
                     "QPushButton:hover { background-color: #353555; color: #aaaadd; }")
            for sym, fn in (("▲", on_up), ("▼", on_down)):
                b = QPushButton(sym)
                b.setFixedSize(18, 18)
                b.setStyleSheet(nav_s)
                b.clicked.connect(fn)
                row_l.addWidget(b)
        if on_link is not None:
            link_b = QPushButton("🔗")
            link_b.setFixedSize(20, 18)
            if link:
                link_b.setToolTip("Linked to an Item Result upgrade — click to unlink")
                link_b.setStyleSheet(
                    "QPushButton { background-color: #1a3a1a; color: #2ecc71; border-radius: 3px;"
                    " font-size: 11px; border: none; }"
                    "QPushButton:hover { background-color: #1e5c1e; }")
            else:
                link_b.setToolTip("Link to an Item Result upgrade (optional)")
                link_b.setStyleSheet(
                    "QPushButton { background-color: #2a2a2a; color: #666666; border-radius: 3px;"
                    " font-size: 11px; border: none; }"
                    "QPushButton:hover { background-color: #3a3a3a; color: #aaaaaa; }")
            link_b.clicked.connect(on_link)
            row_l.addWidget(link_b)
        edit_b = QPushButton("✎")
        edit_b.setFixedSize(20, 18)
        edit_b.setStyleSheet(
            "QPushButton { background-color: #1a2535; color: #5599cc; border-radius: 3px;"
            " font-size: 12px; border: none; }"
            "QPushButton:hover { background-color: #253545; }")
        edit_b.clicked.connect(on_edit)
        row_l.addWidget(edit_b)
        del_b = QPushButton("×")
        del_b.setFixedSize(20, 18)
        del_b.setStyleSheet(
            "QPushButton { background-color: #3a1a1a; color: #ff6666; border-radius: 3px;"
            " font-size: 13px; font-weight: bold; border: none; }"
            "QPushButton:hover { background-color: #5a2222; }")
        del_b.clicked.connect(on_delete)
        row_l.addWidget(del_b)
        return row_w

    def _move_char_task(self, actual_idx, direction):
        if self.selected_char_id is None:
            return None
        tasks = self.char_tasks.get(self.selected_char_id, [])
        if not (0 <= actual_idx < len(tasks)):
            return None
        done = tasks[actual_idx]["done"]
        same_cat = [i for i, t in enumerate(tasks) if t["done"] == done]
        if actual_idx not in same_cat:
            return None
        pos = same_cat.index(actual_idx)
        target_pos = pos + direction
        if not (0 <= target_pos < len(same_cat)):
            return None
        target_idx = same_cat[target_pos]
        tasks[actual_idx], tasks[target_idx] = tasks[target_idx], tasks[actual_idx]
        self.save_data()
        self._refresh_char_tasks_tab()
        return target_idx

    def _edit_char_task(self, actual_idx):
        if self.selected_char_id is None:
            return
        tasks = self.char_tasks.get(self.selected_char_id, [])
        if not (0 <= actual_idx < len(tasks)):
            return
        text, ok = QInputDialog.getText(self, "Edit Task", "Task description:", text=tasks[actual_idx]["text"])
        if ok and text.strip():
            tasks[actual_idx]["text"] = text.strip()
            self.save_data()
            self._refresh_char_tasks_tab()

    def _task_drag_start(self, event, actual_idx, move_fn, container):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        event.accept()
        self._task_drag_state = {
            "actual_idx": actual_idx,
            "last_y": event.globalPosition().y(),
            "move_fn": move_fn,
            "container": container,
        }
        container.grabMouse()

    def _task_drag_move(self, event):
        state = self._task_drag_state
        if not state:
            return
        delta = event.globalPosition().y() - state["last_y"]
        if abs(delta) < 22:
            return
        direction = -1 if delta < 0 else 1
        new_idx = state["move_fn"](state["actual_idx"], direction)
        if new_idx is not None:
            state["actual_idx"] = new_idx
        state["last_y"] = event.globalPosition().y()

    def _task_drag_end(self):
        if self._task_drag_state:
            try:
                self._task_drag_state["container"].releaseMouse()
            except Exception:
                pass
        self._task_drag_state = None

    def eventFilter(self, obj, event):
        tracked = {
            getattr(self, '_char_todo_container', None),
            getattr(self, '_char_done_container', None),
            getattr(self, '_global_todo_rows_container', None),
            getattr(self, '_global_done_rows_container', None),
            getattr(self, '_all_todo_container', None),
            getattr(self, '_all_done_container', None),
        }
        tracked.discard(None)
        if obj in tracked and self._task_drag_state:
            t = event.type()
            if t == QEvent.Type.MouseMove:
                self._task_drag_move(event)
                return True
            if t == QEvent.Type.MouseButtonRelease:
                self._task_drag_end()
                return True
        return super().eventFilter(obj, event)

    def build_all_tasks_page(self):
        page = QWidget()
        page.setStyleSheet("background-color: #121212;")
        root = QVBoxLayout(page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        btn_bar = QWidget()
        btn_bar.setStyleSheet("background-color: #1a1a1a; border-bottom: 1px solid #2a2a2a;")
        bbl = QHBoxLayout(btn_bar)
        bbl.setContentsMargins(16, 8, 16, 8)
        btn_add_g = QPushButton("+ Add General Task")
        btn_add_g.setStyleSheet(
            "QPushButton { background-color: #1a3a2a; color: #2ecc71; border-radius: 3px;"
            " padding: 4px 14px; font-size: 12px; font-weight: bold; border: 1px solid #2ecc71; }"
            "QPushButton:hover { background-color: #2a4a3a; }")
        btn_add_g.clicked.connect(self._add_global_task)
        bbl.addWidget(btn_add_g)
        bbl.addSpacing(8)
        btn_add_c = QPushButton("+ Add Character Task")
        btn_add_c.setStyleSheet(
            "QPushButton { background-color: #1a2a3a; color: #5599cc; border-radius: 3px;"
            " padding: 4px 14px; font-size: 12px; font-weight: bold; border: 1px solid #5599cc; }"
            "QPushButton:hover { background-color: #253545; }")
        btn_add_c.clicked.connect(self._add_char_task_from_global)
        bbl.addWidget(btn_add_c)
        bbl.addStretch()
        self._global_tasks_sort_combo = self._make_sort_combo(self.tasks_sort_mode, self._set_tasks_sort_mode)
        bbl.addWidget(self._global_tasks_sort_combo)
        root.addWidget(btn_bar)

        tab_bar = QTabWidget()
        tab_bar.setStyleSheet(
            "QTabWidget::pane { border: none; background: #121212; }"
            "QTabBar::tab { background: #1a1a1a; color: #aaaaaa; padding: 8px 24px; font-size: 13px; }"
            "QTabBar::tab:selected { background: #121212; color: #e67e22; border-bottom: 2px solid #e67e22; }"
            "QTabBar::tab:hover { background: #222222; }")

        for main_lay_attr, main_cont_attr, frame_attr, rows_lay_attr, rows_cont_attr, label in (
            ("_all_todo_layout", "_all_todo_container", "_global_todo_frame", "_global_todo_rows_layout", "_global_todo_rows_container", "To Do"),
            ("_all_done_layout", "_all_done_container", "_global_done_frame", "_global_done_rows_layout", "_global_done_rows_container", "Completed"),
        ):
            sc = QScrollArea()
            sc.setWidgetResizable(True)
            sc.setStyleSheet("background: transparent; border: none;")
            main_cont = QWidget()
            main_cont.setStyleSheet("background-color: #121212;")
            main_lay = QVBoxLayout(main_cont)
            main_lay.setContentsMargins(24, 18, 24, 24)
            main_lay.setSpacing(16)
            main_lay.setAlignment(Qt.AlignmentFlag.AlignTop)
            setattr(self, main_lay_attr, main_lay)
            setattr(self, main_cont_attr, main_cont)
            main_cont.installEventFilter(self)

            gframe = QFrame()
            gframe.setStyleSheet("background-color: #1a1a2a; border: 1px solid #2a2a3a; border-radius: 6px;")
            gfl = QVBoxLayout(gframe)
            gfl.setContentsMargins(16, 12, 16, 14)
            gfl.setSpacing(6)
            ghdr = QLabel("General Tasks")
            ghdr.setStyleSheet("color: #7777cc; font-size: 14px; font-weight: bold; background: transparent; border: none;")
            gfl.addWidget(ghdr)
            gsep = QFrame()
            gsep.setFrameShape(QFrame.Shape.HLine)
            gsep.setStyleSheet("background-color: #2a2a3a; border: none;")
            gsep.setFixedHeight(1)
            gfl.addWidget(gsep)
            rows_cont = QWidget()
            rows_cont.setStyleSheet("background: transparent;")
            rows_lay = QVBoxLayout(rows_cont)
            rows_lay.setContentsMargins(0, 2, 0, 2)
            rows_lay.setSpacing(4)
            rows_lay.setAlignment(Qt.AlignmentFlag.AlignTop)
            setattr(self, frame_attr, gframe)
            setattr(self, rows_lay_attr, rows_lay)
            setattr(self, rows_cont_attr, rows_cont)
            rows_cont.installEventFilter(self)
            gfl.addWidget(rows_cont)

            sc.setWidget(main_cont)
            tab_bar.addTab(sc, label)

        root.addWidget(tab_bar)
        self.view_stack.addWidget(page)

    def update_all_tasks_page(self):
        self._all_tasks_update_in_progress = True
        for layout, gframe in (
            (self._all_todo_layout, self._global_todo_frame),
            (self._all_done_layout, self._global_done_frame),
        ):
            while layout.count():
                item = layout.takeAt(0)
                w = item.widget()
                if w and w is not gframe:
                    w.deleteLater()
            layout.addWidget(gframe)

        self._refresh_global_tasks_section()

        any_todo = any_done = False
        for char in self.characters:
            cid = char["id"]
            tasks = self.char_tasks.get(cid, [])
            done_total = sum(1 for t in tasks if t["done"])
            total = len(tasks)
            uncompleted = self._sort_indexed([(i, t) for i, t in enumerate(tasks) if not t["done"]], self.tasks_sort_mode, "text")
            completed_t = self._sort_indexed([(i, t) for i, t in enumerate(tasks) if t["done"]], self.tasks_sort_mode, "text")
            for layout, items, drag_cont in (
                (self._all_todo_layout, uncompleted, self._all_todo_container),
                (self._all_done_layout, completed_t, self._all_done_container),
            ):
                if not items:
                    continue
                if layout is self._all_todo_layout:
                    any_todo = True
                else:
                    any_done = True
                frame = QFrame()
                frame.setStyleSheet("background-color: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 6px;")
                fl = QVBoxLayout(frame)
                fl.setContentsMargins(16, 12, 16, 14)
                fl.setSpacing(6)
                hdr_color = "#2ecc71" if total > 0 and done_total == total else "#e67e22"
                hdr_btn = QPushButton(f"➔ {char['name']}  —  {done_total}/{total} done")
                hdr_btn.setStyleSheet(
                    f"QPushButton {{ color: {hdr_color}; font-size: 14px; font-weight: bold;"
                    " background: transparent; border: none; text-align: left; padding: 0; }}"
                    "QPushButton:hover { text-decoration: underline; }")
                hdr_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                hdr_btn.clicked.connect(lambda _, c=cid: self._goto_char_from_tasks(c))
                fl.addWidget(hdr_btn)
                sep = QFrame()
                sep.setFrameShape(QFrame.Shape.HLine)
                sep.setStyleSheet("background-color: #2a2a2a; border: none;")
                sep.setFixedHeight(1)
                fl.addWidget(sep)
                for idx, task in items:
                    move_fn = lambda ii, dd, c=cid: self._move_char_task_global(c, ii, dd)
                    row = self._make_task_row(
                        task,
                        on_check=lambda state, c=cid, i=idx: self._toggle_all_tasks_item(c, i, state),
                        on_up=lambda _, c=cid, i=idx: self._move_char_task_global(c, i, -1),
                        on_down=lambda _, c=cid, i=idx: self._move_char_task_global(c, i, 1),
                        on_edit=lambda _, c=cid, i=idx: self._edit_char_task_global(c, i),
                        on_delete=lambda _, c=cid, i=idx: self._delete_char_task_global(c, i),
                        on_link=lambda _, c=cid, i=idx: self._link_char_task_global(c, i),
                        on_drag_press=lambda e, i=idx, mf=move_fn, dc=drag_cont: self._task_drag_start(e, i, mf, dc),
                        allow_reorder=(self.tasks_sort_mode == "manual"),
                    )
                    fl.addWidget(row)
                if layout is self._all_todo_layout:
                    btn_inline = QPushButton("+ Add Task")
                    btn_inline.setStyleSheet(
                        "QPushButton { background: transparent; color: #555555; border: none;"
                        " font-size: 11px; text-align: left; padding: 2px 0; }"
                        "QPushButton:hover { color: #aaaaaa; }")
                    btn_inline.setCursor(Qt.CursorShape.PointingHandCursor)
                    btn_inline.clicked.connect(lambda _, c=cid, n=char["name"]: self._add_task_inline(c, n))
                    fl.addWidget(btn_inline)
                layout.addWidget(frame)

        if not any_todo and not any(not t["done"] for t in self.global_tasks):
            e = QLabel("No pending tasks")
            e.setStyleSheet("color: #444444; font-size: 14px; background: transparent;")
            self._all_todo_layout.addWidget(e)
        if not any_done and not any(t["done"] for t in self.global_tasks):
            e = QLabel("No completed tasks yet")
            e.setStyleSheet("color: #444444; font-size: 14px; background: transparent;")
            self._all_done_layout.addWidget(e)
        self._all_tasks_update_in_progress = False

    def _toggle_all_tasks_item(self, char_id, task_idx, state):
        if self._all_tasks_update_in_progress:
            return
        tasks = self.char_tasks.get(char_id, [])
        if 0 <= task_idx < len(tasks):
            done = (state != 0)
            task = tasks[task_idx]
            task["done"] = done
            task["closed"] = self._today_str() if done else None
            self._sync_linked_upgrade_from_task(task, done)
            self.save_data()
            self.update_all_tasks_page()

    def _link_char_task_global(self, cid, task_idx):
        tasks = self.char_tasks.get(cid, [])
        if not (0 <= task_idx < len(tasks)):
            return
        task = tasks[task_idx]
        if task.get("linked"):
            task["linked"] = None
        else:
            link = self._prompt_pick_item_upgrade_link(default_char_id=cid)
            if link is None:
                return
            task["linked"] = link
        self.save_data()
        self.update_all_tasks_page()

    def _refresh_global_tasks_section(self):
        if not hasattr(self, '_global_todo_rows_layout'):
            return
        for layout in (self._global_todo_rows_layout, self._global_done_rows_layout):
            while layout.count():
                item = layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
        todo_items = self._sort_indexed([(i, t) for i, t in enumerate(self.global_tasks) if not t["done"]], self.tasks_sort_mode, "text")
        done_items = self._sort_indexed([(i, t) for i, t in enumerate(self.global_tasks) if t["done"]], self.tasks_sort_mode, "text")
        self._global_todo_frame.setVisible(bool(todo_items))
        self._global_done_frame.setVisible(bool(done_items))
        allow_reorder = (self.tasks_sort_mode == "manual")
        for layout, items, container in (
            (self._global_todo_rows_layout, todo_items, self._global_todo_rows_container),
            (self._global_done_rows_layout, done_items, self._global_done_rows_container),
        ):
            for idx, task in items:
                move_fn = lambda ii, dd: self._move_global_task(ii, dd)
                row = self._make_task_row(
                    task,
                    on_check=lambda state, i=idx: self._toggle_global_task(i, state),
                    on_up=lambda _, i=idx: self._move_global_task(i, -1),
                    on_down=lambda _, i=idx: self._move_global_task(i, 1),
                    on_edit=lambda _, i=idx: self._edit_global_task(i),
                    on_delete=lambda _, i=idx: self._delete_global_task(i),
                    on_drag_press=lambda e, i=idx, mf=move_fn, c=container: self._task_drag_start(e, i, mf, c),
                    allow_reorder=allow_reorder,
                )
                layout.addWidget(row)

    def _add_task_inline(self, cid, char_name):
        text, ok = QInputDialog.getText(self, "Add Task", f"Task for {char_name}:")
        if not ok or not text.strip():
            return
        self.char_tasks.setdefault(cid, []).append(
            {"text": text.strip(), "done": False, "opened": self._today_str(), "closed": None})
        self.save_data()
        self.update_all_tasks_page()

    def _add_char_task_from_global(self):
        if not self.characters:
            return
        names = [c["name"] for c in self.characters]
        name, ok = QInputDialog.getItem(self, "Select Character", "Add task to:", names, 0, False)
        if not ok:
            return
        char = next((c for c in self.characters if c["name"] == name), None)
        if not char:
            return
        text, ok2 = QInputDialog.getText(self, "Add Task", f"Task for {name}:")
        if not ok2 or not text.strip():
            return
        self.char_tasks.setdefault(char["id"], []).append(
            {"text": text.strip(), "done": False, "opened": self._today_str(), "closed": None})
        self.save_data()
        self.update_all_tasks_page()

    def _add_global_task(self):
        text, ok = QInputDialog.getText(self, "Add General Task", "Task description:")
        if not ok or not text.strip():
            return
        self.global_tasks.append({"text": text.strip(), "done": False, "opened": self._today_str(), "closed": None})
        self.save_data()
        self._refresh_global_tasks_section()

    def _toggle_global_task(self, idx, state):
        if 0 <= idx < len(self.global_tasks):
            done = (state != 0)
            task = self.global_tasks[idx]
            task["done"] = done
            task["closed"] = self._today_str() if done else None
            self._sync_linked_upgrade_from_task(task, done)
            self.save_data()
            self._refresh_global_tasks_section()

    def _move_global_task(self, actual_idx, direction):
        if not (0 <= actual_idx < len(self.global_tasks)):
            return None
        done = self.global_tasks[actual_idx]["done"]
        same_cat = [i for i, t in enumerate(self.global_tasks) if t["done"] == done]
        if actual_idx not in same_cat:
            return None
        pos = same_cat.index(actual_idx)
        target_pos = pos + direction
        if not (0 <= target_pos < len(same_cat)):
            return None
        target_idx = same_cat[target_pos]
        self.global_tasks[actual_idx], self.global_tasks[target_idx] = (
            self.global_tasks[target_idx], self.global_tasks[actual_idx])
        self.save_data()
        self._refresh_global_tasks_section()
        return target_idx

    def _edit_global_task(self, idx):
        if not (0 <= idx < len(self.global_tasks)):
            return
        text, ok = QInputDialog.getText(
            self, "Edit Task", "Task description:", text=self.global_tasks[idx]["text"])
        if ok and text.strip():
            self.global_tasks[idx]["text"] = text.strip()
            self.save_data()
            self._refresh_global_tasks_section()

    def _delete_global_task(self, idx):
        if 0 <= idx < len(self.global_tasks):
            self.global_tasks.pop(idx)
            self.save_data()
            self._refresh_global_tasks_section()

    def _move_char_task_global(self, cid, actual_idx, direction):
        tasks = self.char_tasks.get(cid, [])
        if not (0 <= actual_idx < len(tasks)):
            return None
        done = tasks[actual_idx]["done"]
        same_cat = [i for i, t in enumerate(tasks) if t["done"] == done]
        if actual_idx not in same_cat:
            return None
        pos = same_cat.index(actual_idx)
        target_pos = pos + direction
        if not (0 <= target_pos < len(same_cat)):
            return None
        ti = same_cat[target_pos]
        tasks[actual_idx], tasks[ti] = tasks[ti], tasks[actual_idx]
        self.save_data()
        self.update_all_tasks_page()
        return ti

    def _edit_char_task_global(self, cid, actual_idx):
        tasks = self.char_tasks.get(cid, [])
        if not (0 <= actual_idx < len(tasks)):
            return
        text, ok = QInputDialog.getText(self, "Edit Task", "Task description:", text=tasks[actual_idx]["text"])
        if ok and text.strip():
            tasks[actual_idx]["text"] = text.strip()
            self.save_data()
            self.update_all_tasks_page()

    def _delete_char_task_global(self, cid, actual_idx):
        tasks = self.char_tasks.get(cid, [])
        if 0 <= actual_idx < len(tasks):
            tasks.pop(actual_idx)
            self.save_data()
            self.update_all_tasks_page()

    def _goto_char_from_tasks(self, char_id):
        for idx, btn in self._tab_buttons.items():
            btn.setChecked(idx == 0)
        self.inline_calendar_drawer.setVisible(False)
        self.enter_character_boss_view(char_id)
        self.boss_schedule_stats_tabs.setCurrentIndex(0)

    def _goto_linked_item_result(self, link):
        if not link:
            return
        char_id = link.get("char_id")
        if not any(c["id"] == char_id for c in self.characters):
            return
        entries = self.char_item_results.get(char_id, [])
        item_idx, upg_idx = link.get("item_idx", -1), link.get("upg_idx", -1)
        is_done = False
        if 0 <= item_idx < len(entries):
            upgrades = entries[item_idx].get("upgrades", [])
            if 0 <= upg_idx < len(upgrades):
                is_done = upgrades[upg_idx].get("done", False)
        self.switch_global_tab(5)
        if hasattr(self, '_item_results_tabs'):
            self._item_results_tabs.setCurrentIndex(1 if is_done else 0)

    def _prompt_add_item_dialog(self, title):
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.setStyleSheet("background-color: #1c1c1c; color: #e0e0e0;")
        layout = QVBoxLayout(dialog)
        layout.setSpacing(8)

        def add_row(label_text, widget):
            row = QHBoxLayout()
            lbl = QLabel(label_text)
            lbl.setFixedWidth(90)
            lbl.setStyleSheet("color: #aaaaaa; font-size: 12px;")
            row.addWidget(lbl)
            row.addWidget(widget, 1)
            layout.addLayout(row)

        field_style = "QLineEdit { background-color: #2a2a2a; color: white; border: 1px solid #3a3a3a; border-radius: 4px; padding: 4px 6px; }"

        item_field = QLineEdit()
        item_field.setStyleSheet(field_style)
        add_row("Item:", item_field)

        upgrade_field = QLineEdit()
        upgrade_field.setPlaceholderText("e.g. Bonus Stats")
        upgrade_field.setStyleSheet(field_style)

        upgrade_list = QListWidget()
        upgrade_list.setStyleSheet(
            "QListWidget { background-color: #2a2a2a; color: white; border: 1px solid #3a3a3a; border-radius: 4px; }"
            "QListWidget::item { padding: 2px 4px; }"
            "QListWidget::item:selected { background-color: #3a4a5a; }")
        upgrade_list.setFixedHeight(90)

        btn_add_upgrade = QPushButton("+ Add")
        btn_add_upgrade.setStyleSheet(
            "QPushButton { background-color: #27ae60; color: white; border-radius: 4px; padding: 4px 12px; font-weight: bold; }"
            "QPushButton:hover { background-color: #1e8449; }")

        def add_upgrade_type():
            text = upgrade_field.text().strip()
            if not text:
                return
            upgrade_list.addItem(text)
            upgrade_field.clear()
            upgrade_field.setFocus()

        btn_add_upgrade.clicked.connect(add_upgrade_type)
        upgrade_field.returnPressed.connect(add_upgrade_type)

        upgrade_add_row = QWidget()
        upgrade_add_hbox = QHBoxLayout(upgrade_add_row)
        upgrade_add_hbox.setContentsMargins(0, 0, 0, 0)
        upgrade_add_hbox.setSpacing(4)
        upgrade_add_hbox.addWidget(upgrade_field, 1)
        upgrade_add_hbox.addWidget(btn_add_upgrade)
        add_row("Upgrade Type:", upgrade_add_row)

        layout.addWidget(upgrade_list)

        btn_remove_upgrade = QPushButton("Remove Selected")
        btn_remove_upgrade.setStyleSheet(
            "QPushButton { background-color: #3a1a1a; color: #ff6666; border-radius: 4px; padding: 3px 10px; font-size: 11px; }"
            "QPushButton:hover { background-color: #5a2222; }")

        def remove_selected():
            for it in upgrade_list.selectedItems():
                upgrade_list.takeItem(upgrade_list.row(it))

        btn_remove_upgrade.clicked.connect(remove_selected)
        rm_row = QHBoxLayout()
        rm_row.addStretch()
        rm_row.addWidget(btn_remove_upgrade)
        layout.addLayout(rm_row)

        hint = QLabel("Add as many upgrade types as you want, then save. You can add more later too.")
        hint.setStyleSheet("color: #666666; font-size: 10px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btn_box.button(QDialogButtonBox.StandardButton.Ok).setStyleSheet(
            "background-color: #27ae60; color: white; font-weight: bold; padding: 4px 14px; border-radius: 4px;")
        btn_box.button(QDialogButtonBox.StandardButton.Cancel).setStyleSheet(
            "background-color: #3a3a3a; color: white; font-weight: bold; padding: 4px 14px; border-radius: 4px;")
        btn_box.accepted.connect(dialog.accept)
        btn_box.rejected.connect(dialog.reject)
        layout.addWidget(btn_box)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        item_name = item_field.text().strip()
        if not item_name:
            return None
        upgrade_types = [upgrade_list.item(i).text() for i in range(upgrade_list.count())]
        leftover = upgrade_field.text().strip()
        if leftover:
            upgrade_types.append(leftover)
        if not upgrade_types:
            return None
        return {"item": item_name, "upgrade_types": upgrade_types}

    def _prompt_upgrade_type_text(self, item_name):
        text, ok = QInputDialog.getText(self, "Add Upgrade Type", f"Upgrade type for {item_name}:")
        if not ok or not text.strip():
            return None
        return text.strip()

    def _make_upgrade_row(self, upgrade, on_check, on_amount_add, on_amount_set, on_type_change, on_result_change, on_target_change, on_delete):
        row_w = QWidget()
        row_w.setStyleSheet("background: transparent;")
        row_l = QHBoxLayout(row_w)
        row_l.setContentsMargins(18, 1, 0, 1)
        row_l.setSpacing(4)

        is_done = upgrade.get("done", False)
        cb = QCheckBox()
        cb.setChecked(is_done)
        cb.setStyleSheet("QCheckBox { background: transparent; } QCheckBox::indicator { width: 16px; height: 16px; }")
        cb.stateChanged.connect(on_check)
        row_l.addWidget(cb)

        tc = "#888888" if is_done else "#cccccc"
        type_edit = QLineEdit(upgrade.get("upgrade_type", ""))
        type_edit.setMaximumWidth(110)
        type_edit.setStyleSheet(
            f"QLineEdit {{ color: {tc}; font-size: 13px; background: transparent; border: 1px solid transparent;"
            " border-radius: 3px; padding: 1px 3px; }"
            "QLineEdit:hover { border: 1px solid #3a3a3a; background-color: #202020; }"
            "QLineEdit:focus { border: 1px solid #5599cc; background-color: #202020; }")
        type_edit.editingFinished.connect(lambda: on_type_change(type_edit.text().strip()))
        row_l.addWidget(type_edit)

        amount_x_lbl = QLabel("x")
        amount_x_lbl.setStyleSheet("color: #f0c040; font-size: 12px; font-weight: bold; background: transparent;")
        row_l.addWidget(amount_x_lbl)

        amount_edit = QLineEdit(str(upgrade.get("amount", 0)))
        amount_edit.setFixedWidth(38)
        amount_edit.setStyleSheet(
            "QLineEdit { background-color: #2a2a2a; color: #f0c040; font-weight: bold; border: 1px solid #3a3a3a;"
            " border-radius: 3px; padding: 2px 4px; font-size: 12px; }")

        def apply_set():
            try:
                value = int(amount_edit.text().strip())
            except ValueError:
                amount_edit.setText(str(upgrade.get("amount", 0)))
                return
            on_amount_set(value)

        amount_edit.editingFinished.connect(apply_set)
        row_l.addWidget(amount_edit)

        amount_input = QLineEdit()
        amount_input.setPlaceholderText("+n")
        amount_input.setFixedWidth(46)
        amount_input.setStyleSheet(
            "QLineEdit { background-color: #2a2a2a; color: white; border: 1px solid #3a3a3a;"
            " border-radius: 3px; padding: 2px 4px; font-size: 11px; }")

        def apply_add():
            try:
                delta = int(amount_input.text().strip())
            except ValueError:
                return
            amount_input.clear()
            on_amount_add(delta)

        amount_input.returnPressed.connect(apply_add)
        row_l.addWidget(amount_input)

        btn_add_amt = QPushButton("+")
        btn_add_amt.setFixedSize(20, 18)
        btn_add_amt.setStyleSheet(
            "QPushButton { background-color: #1a3a1a; color: #2ecc71; border-radius: 3px;"
            " font-size: 12px; font-weight: bold; border: none; }"
            "QPushButton:hover { background-color: #1e5c1e; }")
        btn_add_amt.clicked.connect(apply_add)
        row_l.addWidget(btn_add_amt)

        result_field = QLineEdit(upgrade.get("result", ""))
        result_field.setPlaceholderText("Result...")
        result_field.setFixedWidth(130)
        result_field.setStyleSheet(
            "QLineEdit { background-color: #2a2a2a; color: white; border: 1px solid #3a3a3a;"
            " border-radius: 3px; padding: 2px 4px; font-size: 11px; }")
        result_field.editingFinished.connect(lambda: on_result_change(result_field.text().strip()))
        row_l.addWidget(result_field)

        target_field = QLineEdit(upgrade.get("target", ""))
        target_field.setPlaceholderText("Target...")
        target_field.setFixedWidth(100)
        target_field.setStyleSheet(
            "QLineEdit { background-color: #2a2a2a; color: #e0a030; border: 1px solid #3a3a3a;"
            " border-radius: 3px; padding: 2px 4px; font-size: 11px; }")
        target_field.editingFinished.connect(lambda: on_target_change(target_field.text().strip()))
        row_l.addWidget(target_field)

        opened = upgrade.get("opened")
        closed = upgrade.get("closed")
        if opened or closed:
            date_text = f"Opened {self._fmt_dt_short(opened)}" if opened else ""
            if is_done and closed:
                closed_text = f"Closed {self._fmt_dt_short(closed)}"
                date_text = f"{date_text}  ·  {closed_text}" if date_text else closed_text
            date_lbl = QLabel(date_text)
            date_lbl.setStyleSheet("color: #666666; font-size: 9px; background: transparent;")
            row_l.addWidget(date_lbl)

        row_l.addStretch(1)

        del_b = QPushButton("×")
        del_b.setFixedSize(18, 18)
        del_b.setStyleSheet(
            "QPushButton { background-color: #3a1a1a; color: #ff6666; border-radius: 3px;"
            " font-size: 12px; font-weight: bold; border: none; }"
            "QPushButton:hover { background-color: #5a2222; }")
        del_b.clicked.connect(on_delete)
        row_l.addWidget(del_b)
        return row_w

    def _make_item_group_frame(self, item_entry, upg_rows, on_toggle, on_amount_add, on_amount_set, on_type_change,
                                on_result_change, on_target_change, on_delete_upgrade, on_add_upgrade, on_delete_item, on_rename_item):
        frame = QFrame()
        frame.setStyleSheet("background-color: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 6px;")
        fl = QVBoxLayout(frame)
        fl.setContentsMargins(14, 10, 14, 12)
        fl.setSpacing(4)

        upgrades = item_entry.get("upgrades", [])
        total = len(upgrades)
        done_n = sum(1 for u in upgrades if u.get("done"))

        hdr_row = QHBoxLayout()
        hdr_lbl = QLabel(f"{item_entry.get('item', '')}  —  {done_n}/{total} done")
        hdr_lbl.setStyleSheet("color: #5599cc; font-size: 13px; font-weight: bold; background: transparent;")
        hdr_row.addWidget(hdr_lbl, 1)

        rename_b = QPushButton("✎")
        rename_b.setFixedSize(20, 18)
        rename_b.setStyleSheet(
            "QPushButton { background-color: #1a2535; color: #5599cc; border-radius: 3px;"
            " font-size: 12px; border: none; }"
            "QPushButton:hover { background-color: #253545; }")
        rename_b.clicked.connect(on_rename_item)
        hdr_row.addWidget(rename_b)

        add_upg_b = QPushButton("+ Upgrade Type")
        add_upg_b.setStyleSheet(
            "QPushButton { background-color: #1a2a3a; color: #5599cc; border-radius: 3px; padding: 2px 8px;"
            " font-size: 10px; font-weight: bold; border: 1px solid #5599cc; }"
            "QPushButton:hover { background-color: #253545; }")
        add_upg_b.clicked.connect(on_add_upgrade)
        hdr_row.addWidget(add_upg_b)

        del_item_b = QPushButton("🗑")
        del_item_b.setFixedSize(22, 18)
        del_item_b.setStyleSheet(
            "QPushButton { background-color: #3a1a1a; color: #ff6666; border-radius: 3px;"
            " font-size: 11px; border: none; }"
            "QPushButton:hover { background-color: #5a2222; }")
        del_item_b.clicked.connect(on_delete_item)
        hdr_row.addWidget(del_item_b)

        fl.addLayout(hdr_row)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background-color: #2a2a2a; border: none;")
        sep.setFixedHeight(1)
        fl.addWidget(sep)

        for upg_idx, upgrade in upg_rows:
            row = self._make_upgrade_row(
                upgrade,
                on_check=lambda state, i=upg_idx: on_toggle(i, state),
                on_amount_add=lambda delta, i=upg_idx: on_amount_add(i, delta),
                on_amount_set=lambda value, i=upg_idx: on_amount_set(i, value),
                on_type_change=lambda text, i=upg_idx: on_type_change(i, text),
                on_result_change=lambda text, i=upg_idx: on_result_change(i, text),
                on_target_change=lambda text, i=upg_idx: on_target_change(i, text),
                on_delete=lambda _, i=upg_idx: on_delete_upgrade(i),
            )
            fl.addWidget(row)

        return frame

    def _refresh_char_item_results_tab(self):
        if not hasattr(self, '_char_item_results_todo_layout') or self.selected_char_id is None:
            return
        for layout in (self._char_item_results_todo_layout, self._char_item_results_done_layout):
            while layout.count():
                item = layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
        entries = self.char_item_results.get(self.selected_char_id, [])
        char = next((c for c in self.characters if c["id"] == self.selected_char_id), None)
        name = char["name"] if char else "Character"
        total_upg = sum(len(e.get("upgrades", [])) for e in entries)
        done_upg = sum(1 for e in entries for u in e.get("upgrades", []) if u.get("done"))
        self.char_item_results_header.setText(f"Item Results for {name}  —  {done_upg}/{total_upg} completed")
        undone_layout, done_layout = self._char_item_results_todo_layout, self._char_item_results_done_layout
        any_undone = any_done = False
        sorted_entries = self._sort_indexed(list(enumerate(entries)), self.item_results_sort_mode, "item")
        for idx, entry in sorted_entries:
            upgrades = entry.get("upgrades", [])
            undone_rows = [(i, u) for i, u in enumerate(upgrades) if not u.get("done")]
            done_rows = [(i, u) for i, u in enumerate(upgrades) if u.get("done")]
            common_kwargs = self._item_group_kwargs(self.selected_char_id, idx, self._refresh_char_item_results_tab)
            if undone_rows:
                any_undone = True
                undone_layout.addWidget(self._make_item_group_frame(entry, undone_rows, **common_kwargs))
            if done_rows:
                any_done = True
                done_layout.addWidget(self._make_item_group_frame(entry, done_rows, **common_kwargs))
        if not any_undone:
            e = QLabel("No uncompleted item results")
            e.setStyleSheet("color: #444444; font-size: 12px; background: transparent;")
            undone_layout.addWidget(e)
        if not any_done:
            e = QLabel("No completed item results yet")
            e.setStyleSheet("color: #444444; font-size: 12px; background: transparent;")
            done_layout.addWidget(e)

    def update_pitched_items_page(self):
        if not hasattr(self, 'pitched_items_layout'):
            return
        while self.pitched_items_layout.count():
            w = self.pitched_items_layout.takeAt(0).widget()
            if w: w.deleteLater()

        overall_total = 0
        any_chars = False
        valid_ids = {c["id"] for c in self.characters}
        self.pitched_tracked_chars = [cid for cid in self.pitched_tracked_chars if cid in valid_ids]
        tracked_chars = [c for c in self.characters if c["id"] in self.pitched_tracked_chars]
        for char in tracked_chars:
            cid = char["id"]
            items = self.char_pitched_tracker.setdefault(cid, [])
            any_chars = True
            is_expanded = cid in self._pitched_expanded

            char_total = sum(sum(entry["sources"]) for entry in items)
            overall_total += char_total

            char_frame = QFrame()
            char_frame.setStyleSheet("background-color: #161616; border: 1px solid #2a2a2a; border-radius: 6px;")
            char_fl = QVBoxLayout(char_frame)
            char_fl.setContentsMargins(16, 12, 16, 14)
            char_fl.setSpacing(10)

            char_header = QHBoxLayout()
            toggle_btn = QPushButton("▼" if is_expanded else "▶")
            toggle_btn.setFixedSize(20, 20)
            toggle_btn.setStyleSheet(
                "QPushButton { background: transparent; color: #f0c040; border: none; font-size: 12px; }"
                "QPushButton:hover { color: white; }")
            toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            toggle_btn.clicked.connect(lambda _, c=cid: self._toggle_pitched_char_expanded(c))
            char_header.addWidget(toggle_btn)

            hdr_btn = QPushButton(char['name'])
            hdr_btn.setStyleSheet(
                "QPushButton { color: #f0c040; font-size: 14px; font-weight: bold;"
                " background: transparent; border: none; text-align: left; padding: 0; }"
                "QPushButton:hover { text-decoration: underline; }")
            hdr_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            hdr_btn.clicked.connect(lambda _, c=cid: self._goto_char_from_tasks(c))
            char_header.addWidget(hdr_btn)
            char_header.addStretch()

            btn_remove_char = QPushButton("✕")
            btn_remove_char.setToolTip("Remove this character from Star Force (keeps their tracked items)")
            btn_remove_char.setFixedSize(20, 20)
            btn_remove_char.setStyleSheet(
                "QPushButton { background: transparent; color: #664444; border: none; font-size: 12px; font-weight: bold; }"
                "QPushButton:hover { color: #ff6666; }")
            btn_remove_char.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_remove_char.clicked.connect(lambda _, c=cid: self._remove_pitched_char(c))
            char_header.addWidget(btn_remove_char)

            char_fl.addLayout(char_header)

            if is_expanded:
                sep = QFrame()
                sep.setFrameShape(QFrame.Shape.HLine)
                sep.setStyleSheet("background-color: #2a2a2a; border: none;")
                sep.setFixedHeight(1)
                char_fl.addWidget(sep)

                for idx, entry in enumerate(items):
                    row_frame = QFrame()
                    row_frame.setStyleSheet("background-color: #1f1f1f; border-radius: 4px;")
                    row_hbox = QHBoxLayout(row_frame)
                    row_hbox.setContentsMargins(8, 6, 8, 6)
                    row_hbox.setSpacing(10)

                    icon_path = entry.get("icon_path")
                    icon_lbl = QLabel()
                    icon_lbl.setFixedSize(35, 35)
                    if icon_path and os.path.exists(icon_path):
                        icon_lbl.setPixmap(_scaled_pixmap(icon_path, 35))
                    else:
                        icon_lbl.setText(entry["name"][:1].upper())
                        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                        icon_lbl.setStyleSheet(
                            "background-color: #333333; color: #888888; font-size: 15px; font-weight: bold;"
                            " border-radius: 4px;")
                    row_hbox.addWidget(icon_lbl)

                    name_vbox = QVBoxLayout()
                    name_vbox.setSpacing(0)
                    name_btn = QPushButton(entry["name"].upper())
                    name_btn.setToolTip("Click to rename")
                    name_btn.setStyleSheet(
                        "QPushButton { color: #cccccc; font-size: 11px; font-weight: bold;"
                        " background: transparent; border: none; text-align: left; padding: 0; }"
                        "QPushButton:hover { color: white; text-decoration: underline; }")
                    name_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                    name_btn.clicked.connect(lambda _, c=cid, i=idx: self._rename_pitched_item(c, i))
                    name_vbox.addWidget(name_btn)
                    name_container = QWidget()
                    name_container.setLayout(name_vbox)
                    name_container.setFixedWidth(150)
                    row_hbox.addWidget(name_container)

                    for src_idx in range(PITCHED_SOURCE_COUNT):
                        row_hbox.addWidget(self._make_pitched_source_box(cid, idx, src_idx, entry["sources"][src_idx]))

                    row_hbox.addStretch()
                    row_hbox.addWidget(self._make_pitched_star_box(cid, idx, entry["star"], entry["destructions"]))

                    star_action_vbox = QVBoxLayout()
                    star_action_vbox.setSpacing(2)
                    btn_reset_star = QPushButton("Reset")
                    btn_reset_star.setToolTip("Reset stars to 0")
                    btn_jump_22 = QPushButton("→ 22")
                    btn_jump_22.setToolTip("Jump to 22 stars")
                    for b in (btn_reset_star, btn_jump_22):
                        b.setFixedSize(48, 18)
                        b.setStyleSheet(
                            "QPushButton { background-color: #333333; color: #cccccc; font-size: 10px; border: none; border-radius: 2px; }"
                            "QPushButton:hover { background-color: #444444; }")
                        b.setCursor(Qt.CursorShape.PointingHandCursor)
                    btn_reset_star.clicked.connect(lambda _, c=cid, i=idx: self._set_pitched_star(c, i, 0, "Star Reset"))
                    btn_jump_22.clicked.connect(lambda _, c=cid, i=idx: self._set_pitched_star(c, i, 22, "Jumped to Star"))
                    star_action_vbox.addWidget(btn_reset_star)
                    star_action_vbox.addWidget(btn_jump_22)
                    row_hbox.addLayout(star_action_vbox)

                    log_expanded = (cid, idx) in self._pitched_log_expanded
                    btn_log = QPushButton("📜 Log")
                    btn_log.setToolTip("View this item's history, grouped by star level —\n"
                                       "shows every source/star change and how many\n"
                                       "destructions happened at each star before it\n"
                                       "advanced to the next one.")
                    btn_log.setFixedSize(52, 20)
                    btn_log.setStyleSheet(
                        "QPushButton { background: transparent; color: " + ("#f0c040" if log_expanded else "#666666") +
                        "; border: none; font-size: 11px; }"
                        "QPushButton:hover { color: #f0c040; }")
                    btn_log.setCursor(Qt.CursorShape.PointingHandCursor)
                    btn_log.clicked.connect(lambda _, c=cid, i=idx: self._toggle_pitched_item_log(c, i))
                    row_hbox.addWidget(btn_log)

                    btn_remove = QPushButton("✕")
                    btn_remove.setToolTip("Remove this item")
                    btn_remove.setFixedSize(20, 20)
                    btn_remove.setStyleSheet(
                        "QPushButton { background: transparent; color: #664444; border: none; font-size: 12px; font-weight: bold; }"
                        "QPushButton:hover { color: #ff6666; }")
                    btn_remove.setCursor(Qt.CursorShape.PointingHandCursor)
                    btn_remove.clicked.connect(lambda _, c=cid, i=idx: self._delete_pitched_item(c, i))
                    row_hbox.addWidget(btn_remove)

                    char_fl.addWidget(row_frame)

                    if log_expanded:
                        log_frame = QFrame()
                        log_frame.setStyleSheet("background-color: #17171c; border-radius: 4px;")
                        log_vbox = QVBoxLayout(log_frame)
                        log_vbox.setContentsMargins(12, 6, 12, 6)
                        log_vbox.setSpacing(6)

                        sessions = entry.get("sessions") or [{"star": entry.get("star", 0), "entries": [], "destructions": 0}]
                        for s_idx in range(len(sessions) - 1, -1, -1):
                            session = sessions[s_idx]
                            is_current = (s_idx == len(sessions) - 1)

                            session_box = QVBoxLayout()
                            session_box.setSpacing(2)

                            if is_current:
                                title_text = f"★ {session['star']}  (current)"
                                if session.get("destructions"):
                                    title_text += f"   •   Destructions so far: {session['destructions']}"
                                title_style = "color: #f0c040; font-size: 11px; font-weight: bold; background: transparent;"
                            else:
                                next_star = sessions[s_idx + 1]['star']
                                title_text = f"★ {session['star']} → {next_star}   •   Destructions: {session.get('destructions', 0)}"
                                title_style = "color: #777777; font-size: 11px; font-weight: bold; background: transparent;"
                            title_lbl = QLabel(title_text)
                            title_lbl.setStyleSheet(title_style)
                            session_box.addWidget(title_lbl)

                            entries = session.get("entries", [])
                            if entries:
                                for e_idx in range(len(entries) - 1, -1, -1):
                                    le = entries[e_idx]
                                    line_row = QHBoxLayout()
                                    line_row.setSpacing(6)
                                    line = QLabel(f"    {le['time']}  —  {le['text']}")
                                    line.setStyleSheet("color: #888888; font-size: 10px; background: transparent;")
                                    line_row.addWidget(line)
                                    line_row.addStretch()
                                    btn_del_log = QPushButton("✕")
                                    btn_del_log.setToolTip("Remove this log entry")
                                    btn_del_log.setFixedSize(14, 14)
                                    btn_del_log.setStyleSheet(
                                        "QPushButton { background: transparent; color: #553333; border: none; font-size: 9px; }"
                                        "QPushButton:hover { color: #ff6666; }")
                                    btn_del_log.setCursor(Qt.CursorShape.PointingHandCursor)
                                    btn_del_log.clicked.connect(
                                        lambda _, c=cid, i=idx, si=s_idx, ei=e_idx: self._delete_pitched_log_entry(c, i, si, ei))
                                    line_row.addWidget(btn_del_log)
                                    session_box.addLayout(line_row)
                            else:
                                e = QLabel("    No changes yet")
                                e.setStyleSheet("color: #444444; font-size: 10px; background: transparent;")
                                session_box.addWidget(e)

                            log_vbox.addLayout(session_box)

                        char_fl.addWidget(log_frame)

                btn_add = QPushButton("+ Add Item")
                btn_add.setStyleSheet(
                    "QPushButton { background-color: #27ae60; color: white; border-radius: 3px; padding: 4px 12px;"
                    " font-size: 12px; font-weight: bold; }"
                    "QPushButton:hover { background-color: #1e8449; }")
                btn_add.setCursor(Qt.CursorShape.PointingHandCursor)
                btn_add.clicked.connect(lambda _, c=cid: self._add_pitched_item(c))
                char_fl.addWidget(btn_add, alignment=Qt.AlignmentFlag.AlignLeft)

            self.pitched_items_layout.addWidget(char_frame)

        if not any_chars:
            e = QLabel("No characters added yet — click + Add Character above")
            e.setStyleSheet("color: #444444; font-size: 14px; background: transparent;")
            self.pitched_items_layout.addWidget(e)

        self.pitched_grand_total_lbl.setText(f"GRAND TOTAL   Σ {overall_total}")

    def _add_pitched_char(self):
        available = [c for c in self.characters if c["id"] not in self.pitched_tracked_chars]
        if not available:
            QMessageBox.information(self, "No Characters Available",
                                     "Every character is already added to Star Force.")
            return
        names = [c["name"] for c in available]
        name, ok = QInputDialog.getItem(self, "Add Character", "Choose a character:", names, 0, editable=False)
        if not ok:
            return
        char = next((c for c in available if c["name"] == name), None)
        if not char:
            return
        self.pitched_tracked_chars.append(char["id"])
        self._pitched_expanded.add(char["id"])
        self.save_data()
        self.update_pitched_items_page()

    def _remove_pitched_char(self, cid):
        if cid in self.pitched_tracked_chars:
            self.pitched_tracked_chars.remove(cid)
        self._pitched_expanded.discard(cid)
        self.save_data()
        self.update_pitched_items_page()

    def _toggle_pitched_char_expanded(self, cid):
        if cid in self._pitched_expanded:
            self._pitched_expanded.discard(cid)
        else:
            self._pitched_expanded.add(cid)
        self.update_pitched_items_page()

    def _add_pitched_item(self, cid):
        dialog = QDialog(self)
        dialog.setWindowTitle("Add Pitched Item")
        dialog.setStyleSheet("background-color: #1c1c1c; color: #e0e0e0;")
        layout = QVBoxLayout(dialog)

        lbl = QLabel("Pick a known item, or add a custom one:")
        lbl.setStyleSheet("color: #e0e0e0; font-size: 12px; font-weight: bold; padding-bottom: 4px;")
        layout.addWidget(lbl)

        combo = QComboBox()
        combo.addItem("— Custom Item —")
        for display_name, _fname in PITCHED_ITEMS:
            combo.addItem(display_name)
        layout.addWidget(combo)

        name_edit = QLineEdit()
        name_edit.setPlaceholderText("Item name")
        layout.addWidget(name_edit)

        icon_row = QHBoxLayout()
        btn_browse = QPushButton("Browse Icon...")
        icon_status_lbl = QLabel("(no icon)")
        icon_status_lbl.setStyleSheet("color: #888888; font-size: 11px;")
        chosen_icon = {"path": None}

        def do_browse():
            path, _ = QFileDialog.getOpenFileName(dialog, "Choose Icon Image", "", "Images (*.png *.jpg *.jpeg)")
            if path:
                chosen_icon["path"] = path
                icon_status_lbl.setText(os.path.basename(path))

        btn_browse.clicked.connect(do_browse)
        icon_row.addWidget(btn_browse)
        icon_row.addWidget(icon_status_lbl)
        layout.addLayout(icon_row)

        def on_combo_change(combo_idx):
            is_custom = combo_idx == 0
            name_edit.setEnabled(is_custom)
            btn_browse.setEnabled(is_custom)
            if is_custom:
                name_edit.clear()
                chosen_icon["path"] = None
                icon_status_lbl.setText("(no icon)")
            else:
                display_name, known_fname = PITCHED_ITEMS[combo_idx - 1]
                name_edit.setText(display_name)
                chosen_icon["path"] = os.path.join(ITEMS_ASSETS_DIR, known_fname)
                icon_status_lbl.setText("(built-in icon)")

        combo.currentIndexChanged.connect(on_combo_change)
        on_combo_change(0)

        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btn_box.button(QDialogButtonBox.StandardButton.Ok).setStyleSheet(
            "background-color: #e67e22; color: white; font-weight: bold; padding: 4px 14px; border-radius: 4px;")
        btn_box.button(QDialogButtonBox.StandardButton.Cancel).setStyleSheet(
            "background-color: #3a3a3a; color: white; font-weight: bold; padding: 4px 14px; border-radius: 4px;")
        btn_box.accepted.connect(dialog.accept)
        btn_box.rejected.connect(dialog.reject)
        layout.addWidget(btn_box)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        name = name_edit.text().strip()
        if not name:
            return

        self.char_pitched_tracker.setdefault(cid, []).append(_new_pitched_entry(name, chosen_icon["path"]))
        self.save_data()
        self.update_pitched_items_page()

    def _rename_pitched_item(self, cid, idx):
        items = self.char_pitched_tracker.get(cid, [])
        if not (0 <= idx < len(items)):
            return
        current_name = items[idx]["name"]
        new_name, ok = QInputDialog.getText(self, "Rename Item", "Item name:", text=current_name)
        if not ok or not new_name.strip():
            return
        items[idx]["name"] = new_name.strip()
        self.save_data()
        self.update_pitched_items_page()

    def _delete_pitched_item(self, cid, idx):
        items = self.char_pitched_tracker.get(cid, [])
        if not (0 <= idx < len(items)):
            return
        items.pop(idx)
        # Indices shift after a removal, so drop this character's stale log-expand keys.
        self._pitched_log_expanded = {k for k in self._pitched_log_expanded if k[0] != cid}
        self.save_data()
        self.update_pitched_items_page()

    def _make_pitched_source_box(self, cid, idx, src_idx, value):
        color = PITCHED_SOURCE_COLORS[src_idx % len(PITCHED_SOURCE_COLORS)]
        source_name = PITCHED_SOURCE_NAMES[src_idx] if src_idx < len(PITCHED_SOURCE_NAMES) else f"Source {src_idx + 1}"
        box = QFrame()
        box.setFixedWidth(46)
        box.setToolTip(source_name)
        box.setStyleSheet(f"QFrame {{ background-color: #242424; border: 1px solid {color}; border-radius: 4px; }}")
        vbox = QVBoxLayout(box)
        vbox.setContentsMargins(3, 3, 3, 3)
        vbox.setSpacing(1)

        icon_fname = PITCHED_SOURCE_ICONS[src_idx] if src_idx < len(PITCHED_SOURCE_ICONS) else None
        icon_path = os.path.join(SOURCES_ASSETS_DIR, icon_fname) if icon_fname else None
        if icon_path and os.path.exists(icon_path):
            icon_lbl = QLabel()
            icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            icon_lbl.setPixmap(_scaled_pixmap(icon_path, 22))
            vbox.addWidget(icon_lbl)

        num_lbl = QLabel(str(value))
        num_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        num_lbl.setStyleSheet(f"color: {color}; font-size: 13px; font-weight: bold; border: none; background: transparent;")
        vbox.addWidget(num_lbl)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(2)
        btn_minus = QPushButton("−")
        btn_plus = QPushButton("+")
        for b in (btn_minus, btn_plus):
            b.setFixedSize(18, 16)
            b.setStyleSheet(
                "QPushButton { background-color: #333333; color: #cccccc; font-size: 10px; border: none; border-radius: 2px; }"
                "QPushButton:hover { background-color: #444444; }")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_minus.clicked.connect(lambda: self._adjust_pitched_source(cid, idx, src_idx, -1))
        btn_plus.clicked.connect(lambda: self._adjust_pitched_source(cid, idx, src_idx, 1))
        btn_row.addWidget(btn_minus)
        btn_row.addWidget(btn_plus)
        vbox.addLayout(btn_row)
        return box

    def _make_pitched_star_box(self, cid, idx, star, destructions):
        box = QFrame()
        box.setFixedWidth(74)
        box.setToolTip(f"Destructions: {destructions}\nRight-click: Log a destruction (resets stars to 0)")
        box.setStyleSheet("QFrame { background-color: #242424; border: 1px solid #f0c040; border-radius: 4px; }")
        box.mousePressEvent = lambda event, cid=cid, idx=idx: self._handle_pitched_star_box_click(event, cid, idx)
        vbox = QVBoxLayout(box)
        vbox.setContentsMargins(3, 3, 3, 3)
        vbox.setSpacing(1)

        star_lbl = QLabel(f"★ {star}")
        star_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        star_lbl.setStyleSheet("color: #f0c040; font-size: 13px; font-weight: bold; border: none; background: transparent;")
        vbox.addWidget(star_lbl)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(2)
        btn_minus = QPushButton("−")
        btn_plus = QPushButton("+")
        for b in (btn_minus, btn_plus):
            b.setFixedSize(18, 16)
            b.setStyleSheet(
                "QPushButton { background-color: #333333; color: #cccccc; font-size: 10px; border: none; border-radius: 2px; }"
                "QPushButton:hover { background-color: #444444; }")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_minus.clicked.connect(lambda: self._adjust_pitched_star(cid, idx, -1))
        btn_plus.clicked.connect(lambda: self._adjust_pitched_star(cid, idx, 1))
        btn_row.addWidget(btn_minus)
        btn_row.addWidget(btn_plus)
        vbox.addLayout(btn_row)

        d_lbl = QLabel(f"💀 {destructions}")
        d_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        d_lbl.setStyleSheet("color: #888888; font-size: 9px; border: none; background: transparent;")
        vbox.addWidget(d_lbl)

        return box

    def _handle_pitched_star_box_click(self, event, cid, idx):
        if event.button() == Qt.MouseButton.RightButton:
            self._log_pitched_destruction(cid, idx)
        event.accept()

    def _current_pitched_session(self, entry):
        sessions = entry.setdefault("sessions", [{"star": entry.get("star", 0), "entries": [], "destructions": 0}])
        return sessions[-1]

    def _append_pitched_log(self, entry, text):
        session = self._current_pitched_session(entry)
        session["entries"].append({
            "text": text,
            "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        })

    def _adjust_pitched_source(self, cid, idx, src_idx, delta):
        items = self.char_pitched_tracker.get(cid, [])
        if not (0 <= idx < len(items)):
            return
        entry = items[idx]
        old = entry["sources"][src_idx]
        new = max(0, old + delta)
        entry["sources"][src_idx] = new
        if new != old:
            source_name = PITCHED_SOURCE_NAMES[src_idx] if src_idx < len(PITCHED_SOURCE_NAMES) else f"Source {src_idx + 1}"
            sign = "+1" if new > old else "-1"
            self._append_pitched_log(entry, f"{source_name} {sign} (now {new})")
            if new > old:
                # Adding any of the 5 sources means the item was just destroyed and this
                # material was used for it — count the destruction, but don't reset star
                # or seal the current session (unlike a real, unrevived destruction).
                entry["destructions"] += 1
                self._current_pitched_session(entry)["destructions"] += 1
        self.save_data()
        self.update_pitched_items_page()

    def _adjust_pitched_star(self, cid, idx, delta):
        items = self.char_pitched_tracker.get(cid, [])
        if not (0 <= idx < len(items)):
            return
        entry = items[idx]
        old = entry["star"]
        new = max(0, min(25, old + delta))
        entry["star"] = new
        if new != old:
            sign = "+1" if new > old else "-1"
            self._append_pitched_log(entry, f"Star {sign} (now {new})")
            if new > old:
                # A successful upgrade seals the session for the old star level (its
                # destruction total becomes final) and opens a fresh one for the new level.
                entry.setdefault("sessions", []).append({"star": new, "entries": [], "destructions": 0})
        self.save_data()
        self.update_pitched_items_page()

    def _set_pitched_star(self, cid, idx, new_star, action_label):
        items = self.char_pitched_tracker.get(cid, [])
        if not (0 <= idx < len(items)):
            return
        entry = items[idx]
        old = entry["star"]
        if new_star == old:
            return
        entry["star"] = new_star
        self._append_pitched_log(entry, f"{action_label} (now {new_star})")
        # Jumping/resetting moves to a genuinely different attempt level, so seal the
        # old session and start a fresh one for the new star, same as a normal upgrade.
        entry.setdefault("sessions", []).append({"star": new_star, "entries": [], "destructions": 0})
        self.save_data()
        self.update_pitched_items_page()

    def _log_pitched_destruction(self, cid, idx):
        items = self.char_pitched_tracker.get(cid, [])
        if not (0 <= idx < len(items)):
            return
        entry = items[idx]
        entry["destructions"] += 1
        old_star = entry["star"]
        entry["star"] = 0
        session = self._current_pitched_session(entry)
        session["destructions"] += 1
        self._append_pitched_log(entry, f"Destruction (star reset to 0, total destructions: {entry['destructions']})")
        if old_star != 0:
            entry.setdefault("sessions", []).append({"star": 0, "entries": [], "destructions": 0})
        self.save_data()
        self.update_pitched_items_page()

    def _toggle_pitched_item_log(self, cid, idx):
        key = (cid, idx)
        if key in self._pitched_log_expanded:
            self._pitched_log_expanded.discard(key)
        else:
            self._pitched_log_expanded.add(key)
        self.update_pitched_items_page()

    def _delete_pitched_log_entry(self, cid, idx, session_idx, entry_idx):
        items = self.char_pitched_tracker.get(cid, [])
        if not (0 <= idx < len(items)):
            return
        sessions = items[idx].get("sessions", [])
        if not (0 <= session_idx < len(sessions)):
            return
        entries = sessions[session_idx].get("entries", [])
        if not (0 <= entry_idx < len(entries)):
            return
        entries.pop(entry_idx)
        self.save_data()
        self.update_pitched_items_page()

    # --- Item Results: one handler set shared by the per-character tab and the global page.
    #     `refresh` is whichever view the edit came from; defaults to the global page.

    def _new_upgrade(self, upgrade_type, opened=None):
        return {"upgrade_type": upgrade_type, "amount": 0, "result": "", "target": "", "done": False,
                "opened": opened or self._today_str(), "closed": None}

    def _item_entry(self, cid, item_idx):
        entries = self.char_item_results.get(cid, [])
        return entries[item_idx] if 0 <= item_idx < len(entries) else None

    def _upgrade_at(self, cid, item_idx, upg_idx):
        entry = self._item_entry(cid, item_idx)
        upgrades = entry.get("upgrades", []) if entry else []
        return upgrades[upg_idx] if 0 <= upg_idx < len(upgrades) else None

    def _commit_item_results(self, refresh):
        self.save_data()
        (refresh or self.update_item_results_page)()

    def _add_item_result(self, cid, title, refresh=None):
        data = self._prompt_add_item_dialog(title)
        if data is None:
            return
        today = self._today_str()
        self.char_item_results.setdefault(cid, []).append({
            "item": data["item"], "opened": today,
            "upgrades": [self._new_upgrade(ut, today) for ut in data["upgrade_types"]],
        })
        self._commit_item_results(refresh)

    def _add_char_item_result(self):
        if self.selected_char_id is not None:
            self._add_item_result(self.selected_char_id, "Add Item Result", self._refresh_char_item_results_tab)

    def _add_char_result_from_global(self):
        if not self.characters:
            return
        names = [c["name"] for c in self.characters]
        name, ok = QInputDialog.getItem(self, "Select Character", "Add item result to:", names, 0, False)
        if not ok:
            return
        char = next((c for c in self.characters if c["name"] == name), None)
        if char:
            self._add_item_result(char["id"], f"Add Item Result — {name}")

    def _toggle_item_upgrade_done(self, cid, item_idx, upg_idx, state, refresh=None):
        upg = self._upgrade_at(cid, item_idx, upg_idx)
        if upg is None:
            return
        done = (state != 0)
        upg["done"] = done
        upg["closed"] = self._today_str() if done else None
        self._sync_linked_tasks_from_upgrade(cid, item_idx, upg_idx, done)
        self._commit_item_results(refresh)

    def _add_item_upgrade_amount(self, cid, item_idx, upg_idx, delta, refresh=None):
        upg = self._upgrade_at(cid, item_idx, upg_idx)
        if upg is not None:
            upg["amount"] = upg.get("amount", 0) + delta
            self._commit_item_results(refresh)

    def _set_item_upgrade_field(self, cid, item_idx, upg_idx, field, value, refresh=None):
        if field == "upgrade_type" and not value:
            (refresh or self.update_item_results_page)()
            return
        upg = self._upgrade_at(cid, item_idx, upg_idx)
        if upg is not None:
            upg[field] = value
            self._commit_item_results(refresh)

    def _delete_item_upgrade(self, cid, item_idx, upg_idx, refresh=None):
        entry = self._item_entry(cid, item_idx)
        upgrades = entry.get("upgrades", []) if entry else []
        if not (0 <= upg_idx < len(upgrades)):
            return
        self._clear_or_shift_task_links(cid, item_idx, upg_idx)
        upgrades.pop(upg_idx)
        if not upgrades:
            self.char_item_results[cid].pop(item_idx)
            self._clear_or_shift_task_links(cid, item_idx, None)
        self._commit_item_results(refresh)

    def _add_upgrade_type_to_item(self, cid, item_idx, refresh=None):
        entry = self._item_entry(cid, item_idx)
        if entry is None:
            return
        text = self._prompt_upgrade_type_text(entry.get("item", ""))
        if text is None:
            return
        entry.setdefault("upgrades", []).append(self._new_upgrade(text))
        self._commit_item_results(refresh)

    def _delete_item_entry(self, cid, item_idx, refresh=None):
        if self._item_entry(cid, item_idx) is None:
            return
        self.char_item_results[cid].pop(item_idx)
        self._clear_or_shift_task_links(cid, item_idx, None)
        self._commit_item_results(refresh)

    def _rename_item_entry(self, cid, item_idx, refresh=None):
        entry = self._item_entry(cid, item_idx)
        if entry is None:
            return
        text, ok = QInputDialog.getText(self, "Rename Item", "Item name:", text=entry.get("item", ""))
        if ok and text.strip():
            entry["item"] = text.strip()
            self._commit_item_results(refresh)

    def _item_group_kwargs(self, cid, idx, refresh=None):
        """Callback set for one item's group frame, bound to (cid, item idx) and the originating view."""
        R = refresh
        return dict(
            on_toggle=lambda ui, state: self._toggle_item_upgrade_done(cid, idx, ui, state, R),
            on_amount_add=lambda ui, delta: self._add_item_upgrade_amount(cid, idx, ui, delta, R),
            on_amount_set=lambda ui, value: self._set_item_upgrade_field(cid, idx, ui, "amount", value, R),
            on_type_change=lambda ui, text: self._set_item_upgrade_field(cid, idx, ui, "upgrade_type", text, R),
            on_result_change=lambda ui, text: self._set_item_upgrade_field(cid, idx, ui, "result", text, R),
            on_target_change=lambda ui, text: self._set_item_upgrade_field(cid, idx, ui, "target", text, R),
            on_delete_upgrade=lambda ui: self._delete_item_upgrade(cid, idx, ui, R),
            on_add_upgrade=lambda _: self._add_upgrade_type_to_item(cid, idx, R),
            on_delete_item=lambda _: self._delete_item_entry(cid, idx, R),
            on_rename_item=lambda _: self._rename_item_entry(cid, idx, R),
        )

    def build_item_results_page(self):
        page = QWidget()
        page.setStyleSheet("background-color: #121212;")
        root = QVBoxLayout(page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        btn_bar = QWidget()
        btn_bar.setStyleSheet("background-color: #1a1a1a; border-bottom: 1px solid #2a2a2a;")
        bbl = QHBoxLayout(btn_bar)
        bbl.setContentsMargins(16, 8, 16, 8)
        btn_add = QPushButton("+ Add Item Result")
        btn_add.setStyleSheet(
            "QPushButton { background-color: #1a2a3a; color: #5599cc; border-radius: 3px;"
            " padding: 4px 14px; font-size: 12px; font-weight: bold; border: 1px solid #5599cc; }"
            "QPushButton:hover { background-color: #253545; }")
        btn_add.clicked.connect(self._add_char_result_from_global)
        bbl.addWidget(btn_add)
        bbl.addStretch()
        self._global_items_sort_combo = self._make_sort_combo(self.item_results_sort_mode, self._set_item_results_sort_mode)
        bbl.addWidget(self._global_items_sort_combo)
        root.addWidget(btn_bar)

        tab_bar = QTabWidget()
        self._item_results_tabs = tab_bar
        tab_bar.setStyleSheet(
            "QTabWidget::pane { border: none; background: #121212; }"
            "QTabBar::tab { background: #1a1a1a; color: #aaaaaa; padding: 8px 24px; font-size: 13px; }"
            "QTabBar::tab:selected { background: #121212; color: #5599cc; border-bottom: 2px solid #5599cc; }"
            "QTabBar::tab:hover { background: #222222; }")

        for lay_attr, label in (
            ("_all_item_results_todo_layout", "Uncompleted"),
            ("_all_item_results_done_layout", "Completed"),
        ):
            sc = QScrollArea()
            sc.setWidgetResizable(True)
            sc.setStyleSheet("background: transparent; border: none;")
            main_cont = QWidget()
            main_cont.setStyleSheet("background-color: #121212;")
            main_lay = QVBoxLayout(main_cont)
            main_lay.setContentsMargins(24, 18, 24, 24)
            main_lay.setSpacing(16)
            main_lay.setAlignment(Qt.AlignmentFlag.AlignTop)
            setattr(self, lay_attr, main_lay)
            sc.setWidget(main_cont)
            tab_bar.addTab(sc, label)

        root.addWidget(tab_bar)
        self.view_stack.addWidget(page)

    def build_pitched_items_page(self):
        page = QWidget()
        page.setStyleSheet("background-color: #121212;")
        root = QVBoxLayout(page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        btn_bar = QWidget()
        btn_bar.setStyleSheet("background-color: #1a1a1a; border-bottom: 1px solid #2a2a2a;")
        bbl = QHBoxLayout(btn_bar)
        bbl.setContentsMargins(16, 8, 16, 8)
        self.pitched_grand_total_lbl = QLabel("GRAND TOTAL   Σ 0")
        self.pitched_grand_total_lbl.setStyleSheet("color: #f0c040; font-size: 14px; font-weight: bold;")
        bbl.addWidget(self.pitched_grand_total_lbl)
        bbl.addStretch()
        btn_add_char = QPushButton("+ Add Character")
        btn_add_char.setStyleSheet(
            "QPushButton { background-color: #1a2a3a; color: #5599cc; border-radius: 3px;"
            " padding: 4px 14px; font-size: 12px; font-weight: bold; border: 1px solid #5599cc; }"
            "QPushButton:hover { background-color: #253545; }")
        btn_add_char.clicked.connect(self._add_pitched_char)
        bbl.addWidget(btn_add_char)
        root.addWidget(btn_bar)

        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setStyleSheet("background: transparent; border: none;")
        main_cont = QWidget()
        main_cont.setStyleSheet("background-color: #121212;")
        self.pitched_items_layout = QVBoxLayout(main_cont)
        self.pitched_items_layout.setContentsMargins(24, 18, 24, 24)
        self.pitched_items_layout.setSpacing(16)
        self.pitched_items_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        sc.setWidget(main_cont)
        root.addWidget(sc)

        self.view_stack.addWidget(page)

    def build_item_scanner_page(self):
        page = QWidget()
        page.setStyleSheet("background-color: #121212;")

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background: transparent; border: none;")

        content = QWidget()
        content.setStyleSheet("background-color: #121212;")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(30, 20, 30, 30)
        layout.setSpacing(14)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        title = QLabel("Item Scanner")
        title.setStyleSheet("color: #e67e22; font-size: 22px; font-weight: bold;")
        layout.addWidget(title)

        subtitle = QLabel(
            "Hover an item tooltip anywhere on screen (e.g. in-game) and press F9 — no need to move "
            "your mouse off the item first. The screenshot is grabbed instantly and the tooltip region "
            "is auto-detected. Windows' built-in OCR reads the stats; it isn't perfect on small game "
            "fonts, so the raw text is always shown below to double-check."
        )
        subtitle.setStyleSheet("color: #888888; font-size: 12px;")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        capture_btn = QPushButton("\U0001F4F7  Capture Now (or press F9 anywhere)")
        capture_btn.setStyleSheet("""
            QPushButton { background-color: #e67e22; color: white; font-weight: bold; font-size: 14px;
                          border-radius: 6px; padding: 10px 20px; border: none; }
            QPushButton:hover { background-color: #d35400; }
        """)
        capture_btn.clicked.connect(self._start_item_scan)
        layout.addWidget(capture_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        self._scanner_status_label = QLabel("Hover a tooltip and press F9, or click Capture Now.")
        self._scanner_status_label.setStyleSheet("color: #666666; font-size: 12px;")
        layout.addWidget(self._scanner_status_label)

        row = QHBoxLayout()
        row.setSpacing(16)

        self._scanner_thumb = QLabel("No capture yet")
        self._scanner_thumb.setFixedSize(240, 240)
        self._scanner_thumb.setStyleSheet("background-color: #1a1a1a; border: 1px solid #333; border-radius: 4px; color: #555555;")
        self._scanner_thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(self._scanner_thumb)

        self._scanner_result_frame = QFrame()
        self._scanner_result_frame.setStyleSheet("background-color: #1a1a1a; border: 1px solid #333; border-radius: 4px;")
        self._scanner_result_layout = QVBoxLayout(self._scanner_result_frame)
        self._scanner_result_layout.setContentsMargins(16, 16, 16, 16)
        self._scanner_result_layout.setSpacing(6)
        self._scanner_result_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        placeholder = QLabel("No capture yet.")
        placeholder.setStyleSheet("color: #555555;")
        self._scanner_result_layout.addWidget(placeholder)
        row.addWidget(self._scanner_result_frame, stretch=1)

        layout.addLayout(row)

        raw_label = QLabel("Raw OCR text")
        raw_label.setStyleSheet("color: #888888; font-size: 12px; margin-top: 8px;")
        layout.addWidget(raw_label)

        self._scanner_raw_text = QPlainTextEdit()
        self._scanner_raw_text.setReadOnly(True)
        self._scanner_raw_text.setStyleSheet(
            "background-color: #1a1a1a; color: #999999; border: 1px solid #333; "
            "border-radius: 4px; font-family: Consolas, monospace; font-size: 11px;"
        )
        self._scanner_raw_text.setFixedHeight(120)
        layout.addWidget(self._scanner_raw_text)

        scroll.setWidget(content)
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.addWidget(scroll)

        self.view_stack.addWidget(page)

    def _start_item_scan(self):
        cursor_x, cursor_y = _get_cursor_pos()
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            self._scanner_status_label.setText("Could not access a screen to capture.")
            return
        full_pixmap = screen.grabWindow(0)
        detected_rect = _detect_tooltip_region(full_pixmap, cursor_x, cursor_y)
        if detected_rect is not None:
            self._scanner_status_label.setText(
                "Auto-detected tooltip region (best-effort — check the thumbnail) — reading text…"
            )
            QApplication.processEvents()
            self._process_captured_region(full_pixmap.copy(detected_rect))
        else:
            self._scanner_status_label.setText(
                "Couldn't confidently auto-detect the tooltip — drag a box around it."
            )
            self.showNormal()
            self.activateWindow()
            self._capture_overlay = _RegionCaptureOverlay(
                full_pixmap, self._on_scan_region_selected, self._on_scan_cancelled
            )
            self._capture_overlay.showFullScreen()

    def _on_scan_cancelled(self):
        self.showNormal()
        self._scanner_status_label.setText("Capture cancelled.")

    def _on_scan_region_selected(self, cropped_pixmap: QPixmap):
        self.showNormal()
        self._scanner_status_label.setText("Reading text…")
        QApplication.processEvents()
        self._process_captured_region(cropped_pixmap)

    def _process_captured_region(self, cropped_pixmap: QPixmap):
        self._scanner_thumb.setPixmap(
            cropped_pixmap.scaled(
                self._scanner_thumb.size(), Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        QApplication.processEvents()
        text = self._run_windows_ocr(cropped_pixmap)
        if text is None:
            self._scanner_status_label.setText(
                "OCR failed — Windows OCR language pack may not be installed on this system."
            )
            return
        parsed = self._parse_item_stats(text)
        parsed["stars"] = _count_star_icons(cropped_pixmap)
        self._render_scan_result(parsed, text)
        self._scanner_status_label.setText("Done. Press F9 (while hovering an item) to scan another.")

    def _run_windows_ocr(self, pixmap: QPixmap):
        tmp_dir = tempfile.gettempdir()
        tmp_image_path = os.path.join(tmp_dir, f"boss_scan_{os.getpid()}.png")
        tmp_script_path = os.path.join(tmp_dir, f"boss_scan_ocr_{os.getpid()}.ps1")
        # Small in-game fonts OCR far better upscaled + contrast/sharpness boosted — validated
        # directly (4x LANCZOS + contrast 1.4 + sharpness 2.0 recovered several stat lines and
        # the potential grade word that a plain 3x Qt-scaled image missed entirely).
        arr = _pixmap_to_rgb_array(pixmap)
        img = Image.fromarray(arr)
        img = img.resize((img.width * 4, img.height * 4), Image.LANCZOS)
        img = ImageEnhance.Contrast(img).enhance(1.4)
        img = ImageEnhance.Sharpness(img).enhance(2.0)
        img.save(tmp_image_path, "PNG")
        with open(tmp_script_path, "w", encoding="utf-8") as f:
            f.write(_OCR_POWERSHELL_SCRIPT)
        try:
            proc = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                 "-File", tmp_script_path, "-ImagePath", tmp_image_path],
                capture_output=True, text=True, timeout=20,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        finally:
            for p in (tmp_image_path, tmp_script_path):
                try:
                    os.remove(p)
                except OSError:
                    pass
        if proc.returncode != 0:
            return None
        text = proc.stdout.strip()
        if not text or text == "__OCR_ENGINE_UNAVAILABLE__":
            return None
        return text

    _STAT_NAMES_ALT = r"STR|DEX|INT|LUK|All\s*Stats?|Max\s*HP|Max\s*MP|Attack\s*Power|Magic\s*ATT|Defense"
    # Stat lines look like "STR +217 (40 +117 +60)": base 40, +117 from Star Force/Potential,
    # +60 from Flame — the LAST number in the parens is the flame contribution for that stat.
    # The gap before "(" must not cross into another stat's name — otherwise, when OCR drops a
    # stat's own numbers entirely (common), this would silently grab the NEXT stat's parenthetical
    # and report it as this stat's value instead of correctly finding nothing.
    _STAT_LINE_RE = re.compile(
        r"\b(" + _STAT_NAMES_ALT + r")\b"
        r"(?:(?!\b(?:" + _STAT_NAMES_ALT + r")\b).){0,20}?\(([^)]*)\)",
        re.IGNORECASE,
    )
    _KNOWN_EQUIP_SLOTS = {
        "HAT", "CAPE", "GLOVES", "GLOVE", "SHOES", "TOP", "BOTTOM", "OVERALL", "SHOULDER",
        "BELT", "FACE", "EYE", "EARRINGS", "PENDANT", "RING", "BADGE", "MEDAL", "POCKET",
        "EMBLEM", "WEAPON", "SHIELD", "ARMOR",
    }
    _FLAME_STAT_NAMES = {"STR", "DEX", "INT", "LUK", "ALL STATS", "ALL STAT"}
    # Windows OCR occasionally emits stray box/bullet/private-use glyphs this font can't render
    # (shown as tofu boxes) — strip anything outside plain printable text before parsing/display.
    _STRAY_GLYPH_RE = re.compile(r"[^A-Za-z0-9%/:.,+\-()'\s]")

    def _parse_item_stats(self, text: str) -> dict:
        # This is the real native MapleStory tooltip (STR/DEX/.../Potential), not literal
        # "STARS/FLAME/POTENTIAL" label text — those never appear in the actual game tooltip.
        flat = re.sub(r"\s+", " ", text.replace("•", " ")).strip()
        flat = self._STRAY_GLYPH_RE.sub(" ", flat)
        flat = re.sub(r"\s+", " ", flat).strip()
        parsed = {"category": None, "name": None, "stars": None, "flame_lines": [],
                  "potential_grade": None, "potential_lines": []}
        if not flat:
            return parsed

        name_match = re.match(r"^(.*?)(?:\bUntradable\b|\bDuration\b|\bCombat Power\b)", flat, re.IGNORECASE)
        parsed["name"] = (name_match.group(1).strip() if name_match else flat).strip() or None

        # Only accept a slot word from a known whitelist — OCR often drops the real slot word
        # entirely, and blindly grabbing "the next word" then latches onto unrelated text
        # (e.g. "Required" from "Required Job") instead of failing safely.
        for word_m in re.finditer(r"\b([A-Za-z]+)\b", flat[:flat.upper().find("REQUIRED") if "REQUIRED" in flat.upper() else 200]):
            if word_m.group(1).upper() in self._KNOWN_EQUIP_SLOTS:
                parsed["category"] = word_m.group(1).upper()

        # Flame only applies to primary stats (STR/DEX/INT/LUK/All Stats) for what's tracked here —
        # Max HP/MP, Attack Power, Magic ATT, and Defense are excluded even though they also have
        # a parenthetical breakdown, since they aren't the "flame" values wanted.
        for stat_m in self._STAT_LINE_RE.finditer(flat):
            stat_name = re.sub(r"\s+", " ", stat_m.group(1)).strip().upper()
            if stat_name not in self._FLAME_STAT_NAMES:
                continue
            nums = re.findall(r"[+\-]?\d[\d.,]*%?", stat_m.group(2))
            if nums:
                parsed["flame_lines"].append((stat_name, nums[-1]))

        pot_match = re.search(
            r"Potential\s*:?\s*(Legendary|Unique|Epic|Rare|Exceptional)?\s*:?\s*(.*)$",
            flat, re.IGNORECASE,
        )
        if pot_match:
            parsed["potential_grade"] = pot_match.group(1)
            rest = pot_match.group(2).strip()
            # Strip flavor notes like "(Fully Enhanced)" — not an actual potential stat line.
            rest = re.sub(r"\([^)]*Enhance[^)]*\)", "", rest, flags=re.IGNORECASE).strip()
            # Each real potential line is "<effect text><trailing +N%/-N sec/N>" — split by
            # taking the shortest chunk ending in a number each time, since OCR gives one flat
            # string with no reliable line breaks between the 2-3 bullet lines.
            parsed["potential_lines"] = re.findall(
                r"[A-Za-z][A-Za-z\s:]*?[+\-]?\d+(?:\.\d+)?\s*%?(?:\s*sec)?", rest
            )

        # STARS (Star Force level) isn't in the tooltip text at all — it's a grid of star icons
        # (gold=filled / dark outline=empty) at the top of the tooltip. Counted separately via
        # image analysis in _count_star_icons, not from OCR text — set by the caller.
        return parsed

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())
                item.layout().deleteLater()

    def _render_scan_result(self, parsed: dict, raw_text: str):
        layout = self._scanner_result_layout
        self._clear_layout(layout)

        header_row = QHBoxLayout()
        if parsed.get("category"):
            cat_lbl = QLabel(parsed["category"].upper())
            cat_lbl.setStyleSheet("color: #7c8cff; font-size: 12px; font-weight: bold;")
            header_row.addWidget(cat_lbl)
        name_lbl = QLabel(parsed.get("name") or "(name not detected)")
        name_lbl.setStyleSheet("color: #f0f0f0; font-size: 15px; font-weight: bold;")
        name_lbl.setWordWrap(True)
        header_row.addWidget(name_lbl)
        badge_lbl = QLabel("stats read")
        badge_lbl.setStyleSheet(
            "background-color: #1e3a2a; color: #4ade80; font-size: 10px; font-weight: bold; "
            "border-radius: 8px; padding: 2px 10px;"
        )
        header_row.addWidget(badge_lbl)
        header_row.addStretch()
        layout.addLayout(header_row)

        def add_row(label_text, value_text, value_color):
            row = QHBoxLayout()
            lbl = QLabel(label_text)
            lbl.setFixedWidth(70)
            lbl.setStyleSheet("color: #777777; font-size: 11px; font-weight: bold;")
            row.addWidget(lbl)
            val = QLabel(value_text)
            val.setStyleSheet(f"color: {value_color}; font-size: 13px;")
            val.setWordWrap(True)
            row.addWidget(val, stretch=1)
            layout.addLayout(row)

        if parsed.get("stars") is not None:
            add_row("STARS", f"★ {parsed['stars']}", "#f1c40f")
        else:
            add_row("STARS", "not detected", "#555555")

        flame_lines = parsed.get("flame_lines") or []
        if flame_lines:
            flame_text = "  ".join(f"{name} {val}" for name, val in flame_lines)
            add_row("FLAME", flame_text, "#4ade80")
        else:
            add_row("FLAME", "not detected", "#555555")

        potential_lines = parsed.get("potential_lines") or []
        if potential_lines:
            grade = parsed.get("potential_grade")
            first_label = f"POTENTIAL ({grade})" if grade else "POTENTIAL"
            add_row(first_label, potential_lines[0].strip(), "#c9a8f0")
            for extra_line in potential_lines[1:]:
                add_row("", extra_line.strip(), "#c9a8f0")
        else:
            add_row("POTENTIAL", "not detected", "#555555")

        self._scanner_raw_text.setPlainText(raw_text)

    def update_item_results_page(self):
        for layout in (self._all_item_results_todo_layout, self._all_item_results_done_layout):
            while layout.count():
                item = layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()

        any_undone = any_done = False
        for char in self.characters:
            cid = char["id"]
            entries = self.char_item_results.get(cid, [])
            if not entries:
                continue
            total_upg = sum(len(e.get("upgrades", [])) for e in entries)
            done_upg = sum(1 for e in entries for u in e.get("upgrades", []) if u.get("done"))

            undone_frames, done_frames = [], []
            sorted_entries = self._sort_indexed(list(enumerate(entries)), self.item_results_sort_mode, "item")
            for idx, entry in sorted_entries:
                upgrades = entry.get("upgrades", [])
                undone_rows = [(i, u) for i, u in enumerate(upgrades) if not u.get("done")]
                done_rows = [(i, u) for i, u in enumerate(upgrades) if u.get("done")]
                common_kwargs = self._item_group_kwargs(cid, idx)
                if undone_rows:
                    undone_frames.append(self._make_item_group_frame(entry, undone_rows, **common_kwargs))
                if done_rows:
                    done_frames.append(self._make_item_group_frame(entry, done_rows, **common_kwargs))

            for layout, group_frames in (
                (self._all_item_results_todo_layout, undone_frames),
                (self._all_item_results_done_layout, done_frames),
            ):
                if not group_frames:
                    continue
                if layout is self._all_item_results_todo_layout:
                    any_undone = True
                else:
                    any_done = True
                frame = QFrame()
                frame.setStyleSheet("background-color: #161616; border: 1px solid #2a2a2a; border-radius: 6px;")
                fl = QVBoxLayout(frame)
                fl.setContentsMargins(16, 12, 16, 14)
                fl.setSpacing(10)
                hdr_btn = QPushButton(f"➔ {char['name']}  —  {done_upg}/{total_upg} completed")
                hdr_btn.setStyleSheet(
                    "QPushButton { color: #5599cc; font-size: 14px; font-weight: bold;"
                    " background: transparent; border: none; text-align: left; padding: 0; }"
                    "QPushButton:hover { text-decoration: underline; }")
                hdr_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                hdr_btn.clicked.connect(lambda _, c=cid: self._goto_char_from_tasks(c))
                fl.addWidget(hdr_btn)
                sep = QFrame()
                sep.setFrameShape(QFrame.Shape.HLine)
                sep.setStyleSheet("background-color: #2a2a2a; border: none;")
                sep.setFixedHeight(1)
                fl.addWidget(sep)
                for group_frame in group_frames:
                    fl.addWidget(group_frame)
                layout.addWidget(frame)

        if not any_undone:
            e = QLabel("No uncompleted item results")
            e.setStyleSheet("color: #444444; font-size: 14px; background: transparent;")
            self._all_item_results_todo_layout.addWidget(e)
        if not any_done:
            e = QLabel("No completed item results yet")
            e.setStyleSheet("color: #444444; font-size: 14px; background: transparent;")
            self._all_item_results_done_layout.addWidget(e)

    def delete_character(self, char_id, char_name):
        reply = QMessageBox.question(
            self, "Delete Character",
            f"Are you sure you want to permanently delete \"{char_name}\" and all their data?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.characters = [c for c in self.characters if c["id"] != char_id]
        for d in (self.saved_boss_clears, self.saved_item_drops):
            for k in [k for k in d if k[0] == char_id]:
                del d[k]
        self.char_tasks.pop(char_id, None)
        self.char_item_results.pop(char_id, None)
        self.char_pitched_tracker.pop(char_id, None)
        if char_id in self.pitched_tracked_chars:
            self.pitched_tracked_chars.remove(char_id)
        self.char_completed_weeks = {k for k in self.char_completed_weeks if not k.startswith(f"{char_id}|")}
        for tasks in list(self.char_tasks.values()) + [self.global_tasks]:
            for task in tasks:
                link = task.get("linked")
                if link and link.get("char_id") == char_id:
                    task["linked"] = None
        self.save_data()
        self.update_overview_calendar()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = BossTrackerApp()
    window.show()
    sys.exit(app.exec())