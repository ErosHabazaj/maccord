#!/usr/bin/env python3
"""
Macro Recorder for macOS - GUI (PySide6 / Qt)
=============================================

A windowed front-end for the macro engine in macro_recorder.py.

  * Record key presses and holds (timing is preserved).
  * Replay them into whatever app is focused.
  * Global hotkeys work from ANY app:  F6 = record on/off,  F7 = play.
  * Save / load / delete named macros; set playback speed and repeat count.

macOS permissions required (System Settings > Privacy & Security):
  * Input Monitoring  -> to record keys
  * Accessibility     -> to replay keys
Grant them to whatever launches this (Terminal, or the run.command file).

Threading note: Qt widgets may only be touched from the main thread. The pynput
listener and the playback worker run on background threads, so they only change
engine state or set plain-Python attributes - never Qt widgets. A QTimer on the
main thread polls that state every 100 ms and repaints the UI.
"""

from __future__ import annotations

import sys
import threading
import time

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
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
    MACRO_DIR,
    PLAY_HOTKEY,
    PLAYBACK_START_DELAY,
    RECORD_HOTKEY,
    MacroEngine,
    hotkey_label,
)

COLOR_IDLE = "#9aa0a6"
COLOR_REC = "#e8453c"
COLOR_PLAY = "#2e9e4f"
DEFAULT_TIP = "Tip: F6 and F7 work from any app. Focus your target app before playing."


class MacroWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.engine = MacroEngine()
        self.rec_key = hotkey_label(RECORD_HOTKEY)
        self.play_key = hotkey_label(PLAY_HOTKEY)

        # Plain-Python copies of settings so background threads never read Qt
        # widgets (Qt is not thread-safe).
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

        # Repaint the UI ~10x/second from the main thread.
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(100)
        self.refresh()

    # ---- setup ----------------------------------------------------------
    def _autoload_last(self) -> None:
        last = MACRO_DIR / "last_macro.json"
        if last.exists():
            try:
                self.engine.load(last)
            except Exception:
                pass

    def _build_ui(self) -> None:
        self.setWindowTitle("Macro Recorder")
        self.setMinimumWidth(440)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        # --- status row ---
        status_row = QHBoxLayout()
        self.dot = QLabel("●")
        self.dot.setStyleSheet(f"color: {COLOR_IDLE};")
        self.dot.setFont(QFont("Helvetica", 24))
        status_font = QFont("Helvetica", 18)
        status_font.setBold(True)
        self.status_label = QLabel("READY")
        self.status_label.setFont(status_font)
        status_row.addWidget(self.dot)
        status_row.addWidget(self.status_label)
        status_row.addStretch(1)
        root.addLayout(status_row)

        self.count_label = QLabel("Current macro: 0 events")
        root.addWidget(self.count_label)

        # --- big action buttons ---
        btn_row = QHBoxLayout()
        self.record_btn = QPushButton(f"●  Record ({self.rec_key})")
        self.play_btn = QPushButton(f"▶  Play ({self.play_key})")
        for b in (self.record_btn, self.play_btn):
            b.setMinimumHeight(44)
            b.setFont(QFont("Helvetica", 13))
        self.record_btn.clicked.connect(self.on_record_button)
        self.play_btn.clicked.connect(self.on_play_button)
        btn_row.addWidget(self.record_btn)
        btn_row.addWidget(self.play_btn)
        root.addLayout(btn_row)

        # --- playback options ---
        opt_row = QHBoxLayout()
        opt_row.addWidget(QLabel("Speed:"))
        self.speed_combo = QComboBox()
        self.speed_combo.addItems(["0.25", "0.5", "1.0", "1.5", "2.0", "3.0"])
        self.speed_combo.setCurrentText("1.0")
        opt_row.addWidget(self.speed_combo)
        opt_row.addSpacing(16)
        opt_row.addWidget(QLabel("Repeat:"))
        self.repeat_spin = QSpinBox()
        self.repeat_spin.setRange(1, 999)
        self.repeat_spin.setValue(1)
        opt_row.addWidget(self.repeat_spin)
        opt_row.addStretch(1)
        root.addLayout(opt_row)

        # --- saved macros ---
        root.addWidget(QLabel("Saved macros:"))
        self.macro_list = QListWidget()
        self.macro_list.setMinimumHeight(130)
        self.macro_list.itemDoubleClicked.connect(lambda _: self.on_load())
        root.addWidget(self.macro_list)

        file_row = QHBoxLayout()
        save_btn = QPushButton("Save As…")
        load_btn = QPushButton("Load")
        del_btn = QPushButton("Delete")
        save_btn.clicked.connect(self.on_save)
        load_btn.clicked.connect(self.on_load)
        del_btn.clicked.connect(self.on_delete)
        file_row.addWidget(save_btn)
        file_row.addWidget(load_btn)
        file_row.addWidget(del_btn)
        file_row.addStretch(1)
        root.addLayout(file_row)

        # --- footer tip / transient messages ---
        self.tip_label = QLabel(DEFAULT_TIP)
        self.tip_label.setWordWrap(True)
        self.tip_label.setStyleSheet(f"color: {COLOR_IDLE};")
        root.addWidget(self.tip_label)

    def _start_listener(self) -> None:
        self.listener = keyboard.Listener(on_press=self.on_press, on_release=self.on_release)
        self.listener.start()

    # ---- global listener (background thread; NO Qt calls here) ----------
    def on_press(self, key) -> None:
        if key == RECORD_HOTKEY:
            self.toggle_record()
            return
        if key == PLAY_HOTKEY:
            self.play()
            return
        self.engine.record("press", key)

    def on_release(self, key) -> None:
        if key in (RECORD_HOTKEY, PLAY_HOTKEY):
            return
        self.engine.record("release", key)

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
        if self.engine.recording:
            self.dot.setStyleSheet(f"color: {COLOR_REC};")
            self.status_label.setText("RECORDING")
            self.record_btn.setText(f"■  Stop ({self.rec_key})")
            self.record_btn.setEnabled(True)
            self.play_btn.setEnabled(False)
        elif self.engine.playing:
            self.dot.setStyleSheet(f"color: {COLOR_PLAY};")
            self.status_label.setText("PLAYING")
            self.record_btn.setEnabled(False)
            self.play_btn.setText(f"■  Stop ({self.play_key})")
            self.play_btn.setEnabled(True)
        else:
            self.dot.setStyleSheet(f"color: {COLOR_IDLE};")
            self.status_label.setText("READY")
            self.record_btn.setText(f"●  Record ({self.rec_key})")
            self.record_btn.setEnabled(True)
            has_macro = bool(self.engine.events)
            self.play_btn.setText(f"▶  Play ({self.play_key})")
            self.play_btn.setEnabled(has_macro)

        self.count_label.setText(f"Current macro: {len(self.engine.events)} events")

        if self._message and (time.time() - self._message_time) < 4:
            self.tip_label.setText(self._message)
            self.tip_label.setStyleSheet("color: #1a73e8;")
        else:
            self.tip_label.setText(DEFAULT_TIP)
            self.tip_label.setStyleSheet(f"color: {COLOR_IDLE};")


def main() -> None:
    app = QApplication(sys.argv)
    window = MacroWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
