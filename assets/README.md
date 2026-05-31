# Custom UI assets — drop your images in this folder

Save your PNGs here with the names below. Anything you don't provide just keeps
the current native look, so you can skin it piece by piece.

## Format
- **PNG with transparency** (alpha) for buttons.
- Provide them at **@2x** resolution for a crisp look on the Retina iMac
  (e.g. a button shown at 200×64 should be a 400×128 image).
- Background can be PNG or JPG.

## Filenames I'll look for
| File                     | What it is                                  | States (optional)                  |
|--------------------------|---------------------------------------------|------------------------------------|
| `background.png`         | Whole-window background art                 | —                                  |
| `record.png`            | Record button (idle)                        | `record_hover.png`, `record_pressed.png` |
| `stop_record.png`       | Record button while recording (optional)    | hover / pressed                    |
| `play.png`              | Play button (idle)                          | `play_hover.png`, `play_pressed.png` |
| `stop_play.png`         | Play button while playing (optional)        | hover / pressed                    |
| `save.png` `load.png` `delete.png` | Small file buttons (optional)     | hover / pressed                    |
| `font.ttf` / `font.otf`  | Custom font for the text (optional)         | —                                  |
| `icon.png`               | 1024×1024 app/dock icon (optional)          | —                                  |

Hover/pressed images are optional — one image per button works fine to start,
and I can fake a hover/press effect in code if you don't supply them.

## Also helpful
- Tell me the **window size** you designed the background for (e.g. 480×640),
  or I'll pick one to fit.
- Tell me **where each button sits** on the background (rough x,y is fine — or
  just send a mockup screenshot and I'll match it).
