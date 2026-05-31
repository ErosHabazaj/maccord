# MacCord — pixel-art asset spec

**Golden rule:** draw at the **Canvas** size below (1 art-pixel = 1 PNG-pixel,
no anti-aliasing). I scale everything **×3 with nearest-neighbor**, so 1 of your
pixels becomes a crisp 3×3 block on screen. Every asset shares this same grid,
so they all line up.

Export: **transparent PNG**, exactly the canvas size, no smoothing/scaling.

## Sizes

| File                                   | Canvas (you draw) | On screen (×3) | Notes                              |
|----------------------------------------|-------------------|----------------|------------------------------------|
| `background.png`                       | **180 × 240**     | 540 × 720      | the whole window                   |
| `record.png`                           | **76 × 28**       | 228 × 84       | big Record button (idle)           |
| `record_hover.png` / `record_pressed.png` | 76 × 28        | 228 × 84       | optional click feedback            |
| `stop_record.png` (+ hover/pressed)    | 76 × 28           | 228 × 84       | shown while recording (optional)   |
| `play.png`                             | **76 × 28**       | 228 × 84       | big Play button (idle)             |
| `play_hover.png` / `play_pressed.png`  | 76 × 28           | 228 × 84       | optional                           |
| `stop_play.png` (+ hover/pressed)      | 76 × 28           | 228 × 84       | shown while playing (optional)     |
| `save.png` `load.png` `delete.png`     | **54 × 20**       | 162 × 60       | small buttons (+ optional states)  |
| `status_idle.png` `status_recording.png` `status_playing.png` | 16 × 16 | 48 × 48 | optional status light              |
| `icon.png`                             | **64 × 64** (or bigger square) | — | dock icon; I upscale it to .icns   |
| `font.ttf` / `font.otf`                | —                 | —              | optional pixel font for the text   |

The whole image **is** the button — make the art fill the canvas; transparent
padding inside the canvas is fine.

## Where things sit on the 540 × 720 window (so you don't hide art behind controls)

```
  0  ┌─────────────────────────────┐
     │      header / branding      │   ← put your logo/art up here
120  │   ●  status text            │
     │  [  RECORD  ] [   PLAY   ]   │   ← the two 228×84 buttons (~y140)
220  │   Speed ▼     Repeat #       │   ← themed widget, you don't draw
260  │   Record key F6  Play key F7 │   ← themed widget, you don't draw
320  │   Saved macros:             │
     │   ┌───────────────────────┐ │   ← themed list, you don't draw
     │   │                       │ │
560  │   └───────────────────────┘ │
     │   [ Save ][ Load ][Delete]  │   ← three 162×60 buttons (~y580)
640  │   status / tip text         │
720  └─────────────────────────────┘
```

## You do NOT draw these (I'll style them to match your palette)
- Speed dropdown, Repeat number box
- The two hotkey "Change" buttons
- The "Saved macros" list

For those, just give me a **palette** — e.g. background `#1b1d23`, panel `#262a33`,
text `#e8e8e8`, accent-red `#e23b3b`, button `#2f3540`. I'll theme them to blend in.

## Want chunkier or finer pixels?
This table is ×3. If you want **chunkier** pixels, say so and I'll hand you a ×4
version (halve these canvases). For **finer** detail, I'll do ×2.
