# Macro Recorder for macOS

Record keyboard **presses** and **holds**, then **replay** them into any app.
Timing is preserved, so a 2-second hold replays as a 2-second hold and the gaps
between keystrokes are reproduced exactly.

The GUI is built with **PySide6 (Qt)** — installs via pip, no Homebrew/Tk needed.

## Hotkeys (work from any app)

| Key  | Action                                   |
|------|------------------------------------------|
| `F6` | Start / stop recording                   |
| `F7` | Play the current macro into focused app  |

The window also has on-screen buttons, a saved-macros list, **playback speed**,
and **repeat count**.

---

## 1. Setup (already done on your machine)

The virtual environment and dependencies live in `~/MacroRecorder/.venv`
(`pynput` + `PySide6`). To recreate from scratch:

```bash
cd ~/MacroRecorder
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 2. Grant macOS permissions (required!)

macOS blocks reading and sending keystrokes until you allow it. Grant these to
**the app you launch from** — usually **Terminal**.

Open **System Settings → Privacy & Security**, then add Terminal to BOTH:

1. **Input Monitoring**  → lets it *record* your keypresses
2. **Accessibility**     → lets it *replay* keypresses into other apps

Toggle Terminal **on** in each list, then fully quit and reopen Terminal so the
permissions take effect.

> Launching from VS Code's built-in terminal? Grant the permissions to
> **Visual Studio Code** instead (or just use the standalone Terminal app).

## 3. Run it

**Easiest:** double-click **`run.command`** in Finder (right-click → Open the
first time, since it's an unsigned script).

**Or from a terminal:**

```bash
cd ~/MacroRecorder
./.venv/bin/python macro_recorder_qt.py      # GUI (PySide6)
./.venv/bin/python macro_recorder.py         # optional terminal version
```

---

## How to use

1. Press **F6** (or click **Record**). The status dot turns red.
2. Type / hold keys in whatever app you like.
3. Press **F6** again to stop. The macro auto-saves and the event count updates.
4. Click into the app you want it played into.
5. Press **F7** (or click **Play**). It replays there.

In the window you can also:

- **Save As… / Load / Delete** named macros (stored in `~/MacroRecorder/macros/`).
- Set **Speed** (0.25×–3×) and **Repeat** (1–999 times).
- Click **Stop** while a long / repeating macro is playing to halt it.

---

## Customizing

Edit the **CONFIG** section at the top of `macro_recorder.py`:

```python
RECORD_HOTKEY = keyboard.Key.f6   # change the record hotkey
PLAY_HOTKEY   = keyboard.Key.f7   # change the play hotkey
PLAYBACK_START_DELAY = 0.3        # pause before replay begins
```

The GUI reads these automatically and relabels its buttons to match.

---

## Project layout

```
~/MacroRecorder/
├── macro_recorder_qt.py   ← the GUI (PySide6) — this is what run.command opens
├── macro_recorder.py      ← the macro engine + optional terminal app
├── run.command            ← double-click launcher
├── requirements.txt
├── README.md
├── .venv/                 ← Python env (pynput + PySide6)
└── macros/                ← your saved macros (.json)
```

---

## Troubleshooting

- **Nothing gets recorded / replayed** — almost always permissions. Re-check
  **Input Monitoring** *and* **Accessibility**, then fully quit and reopen
  Terminal.
- **F6 / F7 do nothing** — on some Macs the function-key row sends media keys.
  Press **Fn+F6 / Fn+F7**, or turn on *System Settings → Keyboard → "Use F1,
  F2, etc. as standard function keys"*, or change the hotkeys in CONFIG.
- **The macro types into the wrong app** — playback goes to the focused window.
  Click the target app *before* pressing F7.

## A note on safety

This tool sends real keystrokes to your system. Only replay macros you recorded
yourself, and avoid recording while typing passwords (they'd be saved as plain
text in the macro's `.json` file).
