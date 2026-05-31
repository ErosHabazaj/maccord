#!/usr/bin/env python3
"""
MacCord - macOS macro recorder (PySide6 / Qt), pixel-art skin
=============================================================

A windowed front-end for the macro engine in macro_recorder.py, skinned with
custom pixel-art assets from the assets/ folder.

  * Record key presses and holds (timing is preserved).
  * Replay them into whatever app is focused.
  * Global hotkeys work from ANY app (defaults: F6 = record, F7 = play).
  * Re-bind either hotkey from the window; the choice is saved to settings.json.
  * Save / load / delete named macros; set playback speed and repeat count.

Pixel art is scaled x3 with nearest-neighbour (Qt.FastTransformation) so the
pixels stay crisp. Image buttons swap between idle / hover / pressed art.

The UI font is loaded from assets/font.ttf if present (override with the
MR_FONT env var); otherwise it falls back to Helvetica.

Threading note: Qt widgets may only be touched from the main thread. The pynput
listener and the playback worker run on background threads, so they only change
engine state or set plain-Python attributes - never Qt widgets. A QTimer on the
main thread polls that state every 100 ms and repaints the UI.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QFontDatabase, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QComboBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
from pynput import keyboard

from macro_recorder import (
    DATA_DIR,
    MACRO_DIR,
    PLAY_HOTKEY,
    PLAYBACK_START_DELAY,
    RECORD_HOTKEY,
    MacroEngine,
    deserialize_key,
    hotkey_label,
    serialize_key,
)

# ---- assets & scale --------------------------------------------------------
SCALE = 3  # every asset is rendered at x3 with nearest-neighbour

if getattr(sys, "frozen", False):
    ASSET_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "assets"
else:
    ASSET_DIR = Path(__file__).resolve().parent / "assets"

# ---- palette (sampled from the art) ----------------------------------------
BG = "#263238"
PANEL = "#1b242a"
RED = "#c41411"
BTN_BG = "#32424b"
TEXT = "#e8eaed"
DIM = "#8a949c"
INFO = "#f0c040"
COLOR_IDLE = "#9aa6ad"
COLOR_REC = "#e84e40"
COLOR_PLAY = "#46c265"

DEFAULT_TIP = "Thanks for using MacCord!"
FONT_PX = 14  # base UI font size

SETTINGS_PATH = DATA_DIR / "settings.json"


def build_stylesheet(family: str) -> str:
    return f"""
#MacCordWindow {{ background: {BG}; }}
QLabel {{ color: {TEXT}; background: transparent; font-family: '{family}'; font-size: {FONT_PX}px; }}
QComboBox, QSpinBox {{
    background: {PANEL}; color: {TEXT}; font-family: '{family}'; font-size: {FONT_PX}px;
    border: 1px solid {RED}; border-radius: 3px; padding: 2px 6px; min-height: 20px;
}}
QComboBox::drop-down {{ border: none; width: 16px; }}
QComboBox QAbstractItemView {{
    background: {PANEL}; color: {TEXT};
    selection-background-color: {RED}; selection-color: #ffffff; border: 1px solid {RED};
}}
QListWidget {{
    background: {PANEL}; color: {TEXT}; font-family: '{family}'; font-size: {FONT_PX}px;
    border: 1px solid {RED}; border-radius: 3px;
}}
QListWidget::item {{ padding: 2px 4px; }}
QListWidget::item:selected {{ background: {RED}; color: #ffffff; }}
QPushButton {{
    background: {BTN_BG}; color: {TEXT}; font-family: '{family}'; font-size: {FONT_PX}px;
    border: 1px solid {RED}; border-radius: 3px; padding: 3px 10px;
}}
QPushButton:hover {{ background: #3d4f59; }}
QPushButton:pressed {{ background: {RED}; }}
QPushButton:disabled {{ color: #79828a; border-color: #5a4a4a; background: #2b3940; }}
"""


def load_pixmap(name: str, scale: int = SCALE):
    """Load assets/<name> and scale it ×scale with crisp nearest-neighbour."""
    pm = QPixmap(str(ASSET_DIR / name))
    if pm.isNull():
        return None
    return pm.scaled(
        pm.width() * scale, pm.height() * scale,
        Qt.IgnoreAspectRatio, Qt.FastTransformation,
    )


def load_app_font() -> str:
    """Return the UI font family - from MR_FONT, assets/font.ttf, else Helvetica."""
    path = os.environ.get("MR_FONT") or str(ASSET_DIR / "font.ttf")
    if not Path(path).exists():
        return "Helvetica"
    fid = QFontDatabase.addApplicationFont(path)
    families = QFontDatabase.applicationFontFamilies(fid) if fid != -1 else []
    return families[0] if families else "Helvetica"


class PixmapButton(QAbstractButton):
    """A button drawn entirely from pixmaps (idle / hover / pressed)."""

    def __init__(self, idle, hover=None, pressed=None, parent=None) -> None:
        super().__init__(parent)
        self._idle = idle
        self._hover = hover if hover is not None else idle
        self._pressed = pressed if pressed is not None else idle
        self.active = False  # forced "pressed" look (e.g. while recording)
        if idle is not None:
            self.setFixedSize(idle.size())
        self.setCursor(Qt.PointingHandCursor)
        self.pressed.connect(self.update)
        self.released.connect(self.update)

    def set_active(self, on: bool) -> None:
        if self.active != on:
            self.active = on
            self.update()

    def enterEvent(self, event) -> None:
        self.update()

    def leaveEvent(self, event) -> None:
        self.update()

    def paintEvent(self, event) -> None:
        if self._idle is None:
            return
        painter = QPainter(self)
        if not self.isEnabled():
            painter.setOpacity(0.35)
            pm = self._idle
        elif self.isDown() or self.active:
            pm = self._pressed
        elif self.underMouse():
            pm = self._hover
        else:
            pm = self._idle
        painter.drawPixmap(0, 0, pm)


class MacroWindow(QWidget):
    WIDTH = 180 * SCALE   # 540
    HEIGHT = 240 * SCALE  # 720

    def __init__(self) -> None:
        super().__init__()
        self.engine = MacroEngine()
        self._capturing = None

        self.record_hotkey = RECORD_HOTKEY
        self.play_hotkey = PLAY_HOTKEY
        self._load_settings()
        self.rec_key = hotkey_label(self.record_hotkey)
        self.play_key = hotkey_label(self.play_hotkey)

        self._speed = 1.0
        self._repeat = 1
        self._message = ""
        self._message_time = 0.0
        self._refresh_list = False

        MACRO_DIR.mkdir(parents=True, exist_ok=True)
        self._autoload_last()
        self._build_ui()
        self._start_listener()
        self.populate_macro_list()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(100)
        self.refresh()

    # ---- settings -------------------------------------------------------
    def _load_settings(self) -> None:
        try:
            data = json.loads(SETTINGS_PATH.read_text())
            if "record_hotkey" in data:
                self.record_hotkey = deserialize_key(data["record_hotkey"])
            if "play_hotkey" in data:
                self.play_hotkey = deserialize_key(data["play_hotkey"])
        except Exception:
            pass

    def _save_settings(self) -> None:
        try:
            SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
            SETTINGS_PATH.write_text(
                json.dumps(
                    {
                        "record_hotkey": serialize_key(self.record_hotkey),
                        "play_hotkey": serialize_key(self.play_hotkey),
                    },
                    indent=2,
                )
            )
        except Exception:
            pass

    def _autoload_last(self) -> None:
        last = MACRO_DIR / "last_macro.json"
        if last.exists():
            try:
                self.engine.load(last)
            except Exception:
                pass

    # ---- UI construction ------------------------------------------------
    def _build_ui(self) -> None:
        self.setObjectName("MacCordWindow")
        self.setWindowTitle("MacCord")
        self.setFixedSize(self.WIDTH, self.HEIGHT)
        self.font_family = load_app_font()
        self.setStyleSheet(build_stylesheet(self.font_family))

        icon_pm = load_pixmap("logo.png", scale=8)
        if icon_pm is not None:
            self.setWindowIcon(QIcon(icon_pm))

        # Background image sits behind everything.
        self.bg = QLabel(self)
        bg_pm = load_pixmap("background.png")
        if bg_pm is not None:
            self.bg.setPixmap(bg_pm)
        self.bg.setGeometry(0, 0, self.WIDTH, self.HEIGHT)
        self.bg.lower()

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 20)
        root.setSpacing(9)

        # Logo header.
        logo = QLabel()
        logo_pm = load_pixmap("logoapp.png", scale=3)
        if logo_pm is not None:
            logo.setPixmap(logo_pm)
        root.addWidget(logo, alignment=Qt.AlignHCenter)

        # Status row (dot + text).
        status_row = QHBoxLayout()
        self.dot = QLabel("●")
        self.dot.setFont(QFont(self.font_family, 15))
        self.dot.setStyleSheet(f"color: {COLOR_IDLE}; background: transparent;")
        status_font = QFont(self.font_family, 17)
        status_font.setBold(True)
        self.status_label = QLabel("READY")
        self.status_label.setFont(status_font)
        status_row.addStretch(1)
        status_row.addWidget(self.dot)
        status_row.addWidget(self.status_label)
        status_row.addStretch(1)
        root.addLayout(status_row)

        self.count_label = QLabel("Current macro: 0 events")
        self.count_label.setAlignment(Qt.AlignHCenter)
        root.addWidget(self.count_label)

        # Hero buttons (Record / Play).
        hero = QHBoxLayout()
        hero.setSpacing(16)
        self.record_btn = PixmapButton(
            load_pixmap("record.png"), load_pixmap("record_hover.png"), load_pixmap("record_pressed.png")
        )
        self.play_btn = PixmapButton(
            load_pixmap("play.png"), load_pixmap("play_hover.png"), load_pixmap("play_pressed.png")
        )
        self.record_btn.clicked.connect(self.on_record_button)
        self.play_btn.clicked.connect(self.on_play_button)
        hero.addStretch(1)
        hero.addWidget(self.record_btn)
        hero.addWidget(self.play_btn)
        hero.addStretch(1)
        root.addSpacing(4)
        root.addLayout(hero)
        root.addSpacing(4)

        # Playback options.
        opt = QHBoxLayout()
        opt.addStretch(1)
        opt.addWidget(QLabel("Speed:"))
        self.speed_combo = QComboBox()
        self.speed_combo.addItems(["0.25", "0.5", "1.0", "1.5", "2.0", "3.0"])
        self.speed_combo.setCurrentText("1.0")
        opt.addWidget(self.speed_combo)
        opt.addSpacing(14)
        opt.addWidget(QLabel("Repeat:"))
        self.repeat_spin = QSpinBox()
        self.repeat_spin.setRange(1, 999)
        self.repeat_spin.setValue(1)
        opt.addWidget(self.repeat_spin)
        opt.addStretch(1)
        root.addLayout(opt)

        # Hotkey rebinding.
        hk = QHBoxLayout()
        hk.addStretch(1)
        hk.addWidget(QLabel("Record key:"))
        self.record_key_label = QLabel(self.rec_key)
        self.record_key_label.setStyleSheet(f"color: {RED}; font-weight: bold; background: transparent;")
        hk.addWidget(self.record_key_label)
        self.record_change_btn = QPushButton("Change")
        self.record_change_btn.clicked.connect(self.on_change_record)
        hk.addWidget(self.record_change_btn)
        hk.addSpacing(14)
        hk.addWidget(QLabel("Play key:"))
        self.play_key_label = QLabel(self.play_key)
        self.play_key_label.setStyleSheet(f"color: {RED}; font-weight: bold; background: transparent;")
        hk.addWidget(self.play_key_label)
        self.play_change_btn = QPushButton("Change")
        self.play_change_btn.clicked.connect(self.on_change_play)
        hk.addWidget(self.play_change_btn)
        hk.addStretch(1)
        root.addLayout(hk)

        # Saved macros list.
        root.addWidget(QLabel("Saved macros:"))
        self.macro_list = QListWidget()
        self.macro_list.itemDoubleClicked.connect(lambda _: self.on_load())
        root.addWidget(self.macro_list, stretch=1)

        # File buttons (Save / Load / Delete) with pressed states.
        file_row = QHBoxLayout()
        file_row.setSpacing(12)
        self.save_btn = PixmapButton(load_pixmap("save.png"), None, load_pixmap("save_pressed.png"))
        self.load_btn = PixmapButton(load_pixmap("load.png"), None, load_pixmap("load_pressed.png"))
        self.delete_btn = PixmapButton(load_pixmap("delete.png"), None, load_pixmap("delete_pressed.png"))
        self.save_btn.clicked.connect(self.on_save)
        self.load_btn.clicked.connect(self.on_load)
        self.delete_btn.clicked.connect(self.on_delete)
        file_row.addStretch(1)
        file_row.addWidget(self.save_btn)
        file_row.addWidget(self.load_btn)
        file_row.addWidget(self.delete_btn)
        file_row.addStretch(1)
        root.addLayout(file_row)

        # Footer message.
        self.tip_label = QLabel(DEFAULT_TIP)
        self.tip_label.setWordWrap(True)
        self.tip_label.setAlignment(Qt.AlignHCenter)
        self.tip_label.setStyleSheet(f"color: {DIM}; background: transparent;")
        root.addWidget(self.tip_label)

    def _start_listener(self) -> None:
        self.listener = keyboard.Listener(on_press=self.on_press, on_release=self.on_release)
        self.listener.start()

    # ---- global listener (background thread; NO Qt calls here) ----------
    def on_press(self, key) -> None:
        if self._capturing:
            self._apply_captured_hotkey(key)
            return
        if key == self.record_hotkey:
            self.toggle_record()
            return
        if key == self.play_hotkey:
            self.play()
            return
        self.engine.record("press", key)

    def on_release(self, key) -> None:
        if self._capturing:
            return
        if key in (self.record_hotkey, self.play_hotkey):
            return
        self.engine.record("release", key)

    # ---- hotkey capture -------------------------------------------------
    def on_change_record(self) -> None:
        self._toggle_capture("record")

    def on_change_play(self) -> None:
        self._toggle_capture("play")

    def _toggle_capture(self, target: str) -> None:
        if self.engine.recording or self.engine.playing:
            self._notify("Finish recording / playing first.")
            return
        if self._capturing == target:
            self._capturing = None
            self._notify("Cancelled.")
        else:
            self._capturing = target
            self._notify(f"Press the new key for {target.capitalize()}  (Esc to cancel).")
        self.refresh()

    def _apply_captured_hotkey(self, key) -> None:
        target = self._capturing
        self._capturing = None
        if key == keyboard.Key.esc:
            self._notify("Cancelled.")
            return
        other = self.play_hotkey if target == "record" else self.record_hotkey
        if key == other:
            self._notify(f"{hotkey_label(key)} is already the other hotkey - pick a different key.")
            return
        if target == "record":
            self.record_hotkey = key
        else:
            self.play_hotkey = key
        self.rec_key = hotkey_label(self.record_hotkey)
        self.play_key = hotkey_label(self.play_hotkey)
        self._save_settings()
        self._notify(f"{target.capitalize()} hotkey set to {hotkey_label(key)}.")

    # ---- thread-safe actions (engine state + plain attrs only) ----------
    def toggle_record(self) -> None:
        if self.engine.playing:
            self._notify("Can't record while a macro is playing.")
            return
        if self.engine.recording:
            self.engine.stop_recording()
            self.engine.save(MACRO_DIR / "last_macro.json")
            self._refresh_list = True
            self._notify(f"Recorded {len(self.engine.events)} events (auto-saved).")
        else:
            self.engine.start_recording()
            self._notify(f"Recording... press {self.rec_key} again to stop.")

    def play(self) -> None:
        if self.engine.recording:
            self._notify("Stop recording first.")
            return
        if self.engine.playing:
            return
        if not self.engine.events:
            self._notify("No macro to play - record something first.")
            return
        threading.Thread(target=self._play_worker, daemon=True).start()

    def _play_worker(self) -> None:
        self.engine.play(speed=self._speed, start_delay=PLAYBACK_START_DELAY, repeat=self._repeat)
        self._notify("Done.")

    def _notify(self, text: str) -> None:
        self._message = text
        self._message_time = time.time()

    # ---- button handlers (main thread; Qt allowed) ----------------------
    def on_record_button(self) -> None:
        self.toggle_record()
        self.refresh()

    def on_play_button(self) -> None:
        if self.engine.playing:
            self.engine.request_stop()
            self._notify("Stopping...")
        else:
            self.play()
        self.refresh()

    def on_save(self) -> None:
        if not self.engine.events:
            QMessageBox.information(self, "Nothing to save", "Record a macro first.")
            return
        name, ok = QInputDialog.getText(self, "Save macro", "Name for this macro:")
        if not ok or not name.strip():
            return
        name = name.strip()
        if not name.endswith(".json"):
            name += ".json"
        self.engine.save(MACRO_DIR / name)
        self.populate_macro_list()
        self._notify(f"Saved {name}")

    def on_load(self) -> None:
        name = self._selected_macro()
        if not name:
            QMessageBox.information(self, "Load macro", "Select a macro from the list first.")
            return
        try:
            self.engine.load(MACRO_DIR / name)
        except Exception as exc:
            QMessageBox.critical(self, "Load failed", str(exc))
            return
        self._notify(f"Loaded {name} ({len(self.engine.events)} events)")
        self.refresh()

    def on_delete(self) -> None:
        name = self._selected_macro()
        if not name:
            return
        confirm = QMessageBox.question(self, "Delete macro", f"Delete '{name}'?")
        if confirm == QMessageBox.StandardButton.Yes:
            (MACRO_DIR / name).unlink(missing_ok=True)
            self.populate_macro_list()
            self._notify(f"Deleted {name}")

    def closeEvent(self, event) -> None:
        try:
            self.listener.stop()
        except Exception:
            pass
        event.accept()

    # ---- helpers --------------------------------------------------------
    def _selected_macro(self):
        item = self.macro_list.currentItem()
        return item.text() if item else None

    def populate_macro_list(self) -> None:
        self.macro_list.clear()
        for path in sorted(MACRO_DIR.glob("*.json")):
            self.macro_list.addItem(path.name)

    # ---- periodic UI refresh (main thread) ------------------------------
    def _tick(self) -> None:
        try:
            self._speed = float(self.speed_combo.currentText())
        except ValueError:
            self._speed = 1.0
        self._repeat = max(1, self.repeat_spin.value())

        if self._refresh_list:
            self._refresh_list = False
            self.populate_macro_list()

        self.refresh()

    def refresh(self) -> None:
        busy = self.engine.recording or self.engine.playing

        if self.engine.recording:
            self.dot.setStyleSheet(f"color: {COLOR_REC}; background: transparent;")
            self.status_label.setText("RECORDING")
            self.record_btn.set_active(True)
            self.record_btn.setEnabled(True)
            self.play_btn.set_active(False)
            self.play_btn.setEnabled(False)
        elif self.engine.playing:
            self.dot.setStyleSheet(f"color: {COLOR_PLAY}; background: transparent;")
            self.status_label.setText("PLAYING")
            self.record_btn.set_active(False)
            self.record_btn.setEnabled(False)
            self.play_btn.set_active(True)
            self.play_btn.setEnabled(True)
        else:
            self.dot.setStyleSheet(f"color: {COLOR_IDLE}; background: transparent;")
            self.status_label.setText("READY")
            self.record_btn.set_active(False)
            self.record_btn.setEnabled(True)
            self.play_btn.set_active(False)
            self.play_btn.setEnabled(bool(self.engine.events))

        self.record_key_label.setText("press…" if self._capturing == "record" else self.rec_key)
        self.play_key_label.setText("press…" if self._capturing == "play" else self.play_key)
        self.record_change_btn.setText("Cancel" if self._capturing == "record" else "Change")
        self.play_change_btn.setText("Cancel" if self._capturing == "play" else "Change")
        self.record_change_btn.setEnabled(not busy and self._capturing in (None, "record"))
        self.play_change_btn.setEnabled(not busy and self._capturing in (None, "play"))

        for b in (self.save_btn, self.load_btn, self.delete_btn):
            b.setEnabled(not busy)

        self.count_label.setText(f"Current macro: {len(self.engine.events)} events")

        if self._message and (time.time() - self._message_time) < 4:
            self.tip_label.setText(self._message)
            self.tip_label.setStyleSheet(f"color: {INFO}; background: transparent;")
        else:
            self.tip_label.setText(DEFAULT_TIP)
            self.tip_label.setStyleSheet(f"color: {DIM}; background: transparent;")


def main() -> None:
    app = QApplication(sys.argv)

    if os.environ.get("MR_SELFTEST") == "1":
        MacroWindow._start_listener = lambda self: None
        MacroWindow()
        print("MR_SELFTEST OK")
        return

    window = MacroWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
