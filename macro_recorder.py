#!/usr/bin/env python3
"""
Macro Recorder for macOS
========================

A small, fully-functioning keyboard macro recorder.

  * Records key PRESSES and key HOLDS. Timing is preserved, so a long hold
    replays as a long hold and the gaps between keys are reproduced too.
  * Replays the recorded macro into whatever app is focused, triggered by a
    GLOBAL hotkey that works from ANY application.
  * Saves / loads named macros to disk so they survive restarts.

Built on `pynput`, which talks to the macOS input system. Because of that,
macOS requires you to grant the app that runs this script two permissions
(see README.md): **Accessibility** and **Input Monitoring**.

Default hotkeys (change them in the CONFIG section below):
    F6  - start / stop recording
    F7  - play the current macro into the focused app

Save, load, list and quit are done from the text menu in this terminal.
"""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

try:
    from pynput import keyboard
except ImportError:
    sys.exit(
        "\nThe 'pynput' package is not installed.\n"
        "Activate the project's virtual environment and install it:\n"
        "    source ~/MacroRecorder/.venv/bin/activate\n"
        "    pip install pynput\n"
    )


# ----------------------------------------------------------------------------
# CONFIG - tweak these to taste
# ----------------------------------------------------------------------------
RECORD_HOTKEY = keyboard.Key.f6      # toggle recording on/off
PLAY_HOTKEY = keyboard.Key.f7        # replay the current macro

PLAYBACK_SPEED = 1.0                 # 1.0 = real time, 2.0 = twice as fast
PLAYBACK_START_DELAY = 0.3           # seconds to wait before replay begins,
                                     # so you have time to release the hotkey

# Where macros are stored (a "macros" folder next to this script).
MACRO_DIR = Path(__file__).resolve().parent / "macros"

# Keys used to control the app - these are never recorded into a macro.
CONTROL_KEYS = {RECORD_HOTKEY, PLAY_HOTKEY}


# ----------------------------------------------------------------------------
# Key (de)serialization - turn pynput key objects into plain JSON and back.
#
# pynput represents keys two ways:
#   * keyboard.Key      -> named special keys (space, enter, shift, cmd, f6...)
#   * keyboard.KeyCode  -> character keys (a, b, 1, $) or a raw virtual-key code
# We convert both into simple dicts so a macro can be written to a JSON file.
# ----------------------------------------------------------------------------
def serialize_key(key) -> dict:
    """Convert a pynput key object into a JSON-friendly dict."""
    if isinstance(key, keyboard.Key):
        return {"type": "special", "value": key.name}
    if isinstance(key, keyboard.KeyCode):
        if key.char is not None:
            return {"type": "char", "value": key.char}
        # Some keys have no printable character - fall back to its code.
        return {"type": "vk", "value": key.vk}
    raise ValueError(f"Cannot serialize key: {key!r}")


def deserialize_key(data: dict):
    """Rebuild a pynput key object from the dict produced by serialize_key."""
    kind = data["type"]
    if kind == "special":
        return keyboard.Key[data["value"]]
    if kind == "char":
        return keyboard.KeyCode.from_char(data["value"])
    if kind == "vk":
        return keyboard.KeyCode.from_vk(data["value"])
    raise ValueError(f"Cannot deserialize key data: {data!r}")


def hotkey_label(key) -> str:
    """Human-friendly name for a hotkey, e.g. 'F6'."""
    if isinstance(key, keyboard.Key):
        return key.name.upper()
    if isinstance(key, keyboard.KeyCode) and key.char:
        return key.char.upper()
    return str(key)


# ----------------------------------------------------------------------------
# MacroEngine - stores the events and knows how to record and replay them.
# ----------------------------------------------------------------------------
class MacroEngine:
    def __init__(self) -> None:
        self.events: list[dict] = []
        self.recording = False
        self.playing = False
        self._start_time = 0.0
        self._stop_requested = False
        self._controller = keyboard.Controller()

    # ---- recording -------------------------------------------------------
    def start_recording(self) -> None:
        self.events = []
        self._start_time = time.perf_counter()
        self.recording = True

    def stop_recording(self) -> None:
        self.recording = False

    def record(self, action: str, key) -> None:
        """Append one press/release event, timestamped from the recording start."""
        if not self.recording:
            return
        offset = time.perf_counter() - self._start_time
        self.events.append(
            {"t": offset, "action": action, "key": serialize_key(key)}
        )

    # ---- playback --------------------------------------------------------
    def play(
        self,
        speed: float = 1.0,
        start_delay: float = 0.0,
        repeat: int = 1,
    ) -> None:
        """Replay the recorded events into the currently focused app.

        speed       playback speed multiplier (2.0 = twice as fast)
        start_delay seconds to wait before the first key is sent
        repeat      how many times to play the macro back-to-back
        """
        if not self.events:
            print("\n[!] Nothing to play - record something first.", flush=True)
            return
        if self.playing:
            return

        self.playing = True
        self._stop_requested = False
        held: list = []  # keys pressed but not yet released
        try:
            if start_delay > 0:
                time.sleep(start_delay)

            for _ in range(max(1, repeat)):
                if self._stop_requested:
                    break
                # Start timing from the first event so a leading pause is dropped.
                prev = self.events[0]["t"]
                for ev in self.events:
                    if self._stop_requested:
                        break
                    delay = (ev["t"] - prev) / speed
                    if delay > 0:
                        time.sleep(delay)
                    prev = ev["t"]

                    key = deserialize_key(ev["key"])
                    if ev["action"] == "press":
                        self._controller.press(key)
                        held.append(key)
                    else:
                        self._controller.release(key)
                        if key in held:
                            held.remove(key)
        finally:
            # Release anything still held so we never leave a key "stuck down".
            for key in held:
                try:
                    self._controller.release(key)
                except Exception:
                    pass
            self.playing = False

    def request_stop(self) -> None:
        """Ask an in-progress playback to stop as soon as possible."""
        self._stop_requested = True

    # ---- persistence -----------------------------------------------------
    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.events, indent=2))

    def load(self, path: Path) -> None:
        self.events = json.loads(path.read_text())


# ----------------------------------------------------------------------------
# MacroApp - wires the global keyboard listener to the engine, plus a small
# text menu running in the terminal for save / load / list / quit.
# ----------------------------------------------------------------------------
class MacroApp:
    def __init__(self) -> None:
        self.engine = MacroEngine()
        self._print_lock = threading.Lock()

    def say(self, message: str) -> None:
        """Thread-safe print (the listener runs on its own thread)."""
        with self._print_lock:
            print(message, flush=True)

    # ---- global listener callbacks --------------------------------------
    def on_press(self, key) -> None:
        if key == RECORD_HOTKEY:
            self.toggle_recording()
            return
        if key == PLAY_HOTKEY:
            self.start_playback()
            return
        # Anything else is recorded (only has an effect while recording).
        self.engine.record("press", key)

    def on_release(self, key) -> None:
        if key in CONTROL_KEYS:
            return
        self.engine.record("release", key)

    # ---- actions ---------------------------------------------------------
    def toggle_recording(self) -> None:
        if self.engine.playing:
            self.say("\n[!] Can't record while a macro is playing.")
            return
        if self.engine.recording:
            self.engine.stop_recording()
            self.say(
                f"\n[#] Recording STOPPED - {len(self.engine.events)} events captured."
            )
            # Auto-save so the macro survives even if you forget to save it.
            self.engine.save(MACRO_DIR / "last_macro.json")
        else:
            self.engine.start_recording()
            self.say(
                f"\n[#] Recording STARTED - press {hotkey_label(RECORD_HOTKEY)} again to stop."
            )

    def start_playback(self) -> None:
        if self.engine.recording:
            self.say(f"\n[!] Stop recording ({hotkey_label(RECORD_HOTKEY)}) before playing.")
            return
        # Play on a separate thread so the listener stays responsive and we
        # don't synthesize keystrokes from inside the listener callback.
        threading.Thread(
            target=self.engine.play,
            args=(PLAYBACK_SPEED, PLAYBACK_START_DELAY),
            daemon=True,
        ).start()
        self.say("\n[>] Playing macro...")

    # ---- menu commands ---------------------------------------------------
    def cmd_save(self) -> None:
        if not self.engine.events:
            self.say("Nothing to save yet - record a macro first.")
            return
        name = input("Save macro as (name): ").strip()
        if not name:
            self.say("Cancelled.")
            return
        if not name.endswith(".json"):
            name += ".json"
        path = MACRO_DIR / name
        self.engine.save(path)
        self.say(f"Saved -> {path}")

    def cmd_load(self) -> None:
        macros = self.saved_macros()
        if not macros:
            self.say("No saved macros found.")
            return
        self.cmd_list()
        name = input("Load which macro (name or number): ").strip()
        path = self._resolve_macro(name, macros)
        if path is None:
            self.say("Not found.")
            return
        self.engine.load(path)
        self.say(
            f"Loaded {path.name} ({len(self.engine.events)} events). "
            f"Press {hotkey_label(PLAY_HOTKEY)} to play."
        )

    def cmd_list(self) -> None:
        macros = self.saved_macros()
        if not macros:
            self.say("No saved macros yet.")
            return
        self.say("Saved macros:")
        for i, p in enumerate(macros, 1):
            self.say(f"  {i}. {p.name}")

    def saved_macros(self) -> list[Path]:
        return sorted(MACRO_DIR.glob("*.json"))

    def _resolve_macro(self, name: str, macros: list[Path]):
        if name.isdigit():
            idx = int(name) - 1
            return macros[idx] if 0 <= idx < len(macros) else None
        if not name.endswith(".json"):
            name += ".json"
        path = MACRO_DIR / name
        return path if path.exists() else None

    # ---- UI text ---------------------------------------------------------
    def print_banner(self) -> None:
        rec, play = hotkey_label(RECORD_HOTKEY), hotkey_label(PLAY_HOTKEY)
        self.say("=" * 60)
        self.say("  Macro Recorder for macOS")
        self.say("=" * 60)
        self.say(f"  {rec:>4}   start / stop recording   (works in any app)")
        self.say(f"  {play:>4}   play current macro       (works in any app)")
        self.print_help()

    def print_help(self) -> None:
        self.say(
            "\nMenu commands (type these here in the terminal):\n"
            "  r   record on/off       p   play\n"
            "  s   save macro          l   load macro\n"
            "  ls  list macros         h   help\n"
            "  q   quit"
        )

    # ---- main loop -------------------------------------------------------
    def run(self) -> None:
        MACRO_DIR.mkdir(parents=True, exist_ok=True)

        # Auto-load the most recent recording if there is one.
        last = MACRO_DIR / "last_macro.json"
        if last.exists():
            try:
                self.engine.load(last)
            except (OSError, json.JSONDecodeError):
                pass

        listener = keyboard.Listener(
            on_press=self.on_press, on_release=self.on_release
        )
        listener.start()

        self.print_banner()
        try:
            self.menu_loop()
        finally:
            listener.stop()
            self.say("\nGoodbye.")

    def menu_loop(self) -> None:
        while True:
            try:
                choice = input("\nmacro> ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                return

            if choice in ("q", "quit", "exit"):
                return
            elif choice in ("r", "rec", "record"):
                self.toggle_recording()
            elif choice in ("p", "play"):
                self.start_playback()
            elif choice in ("s", "save"):
                self.cmd_save()
            elif choice in ("l", "load"):
                self.cmd_load()
            elif choice in ("ls", "list"):
                self.cmd_list()
            elif choice in ("h", "help", "?"):
                self.print_help()
            elif choice == "":
                continue
            else:
                self.say("Unknown command. Type 'h' for help.")


def main() -> None:
    MacroApp().run()


if __name__ == "__main__":
    main()
