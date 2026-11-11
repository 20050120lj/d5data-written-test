# Upload Your Resume — Figma implementation

A pixel-close, dependency-free implementation of the Figma frame for the front-end internship
exercise. Plain HTML + CSS + a small amount of vanilla JS: no framework, no build step, no CDN.

## Run

Open `index.html` directly, or serve it:

```bash
python -m http.server 8080   # then http://127.0.0.1:8080/
```

| File | Role |
| --- | --- |
| `index.html` | Semantic markup + inline SVG illustration |
| `style.css` | All styling: layout, states, responsive rules |
| `script.js` | Upload interaction: click / drag-drop / validation / file name |
| `preview-desktop.png` | 1440 × 900 render |
| `preview-tablet.png` | 760 × 1200 render (stacked layout) |

## What was matched, and how

Colours were sampled from the exported design rather than eyeballed:

| Token | Value | Used for |
| --- | --- | --- |
| `--primary` | `#005EFF` | Finish button, progress dots, key icon accents |
| `--secondary` | `#61AFFF` | Last step button |
| `--tint` | `#F0FBFF` | Dropzone background |
| `--ink` | `#1A1D21` | Headline |
| `--muted` | `#9AA3AF` | Lede and file-size hint |

Structure mirrors the frame: two columns (copy + illustration on the left, a raised card on the
right), the card stacking title → dashed dropzone → button pair → three-dot stepper.

Type scale follows the frame's hierarchy: 17 px / 500 for the "Finish!" eyebrow, a 42 → 30 px
fluid headline, 14.5 px / 1.95 grey lede, 20 px card title.

## Interaction (the "加分项" items)

| Brief item | Implementation |
| --- | --- |
| Click the upload area to open the file picker | The dropzone **is** a `<label for="file-input">`, so it works without JS and with keyboard (`Enter`/`Space` handled explicitly for parity) |
| Buttons have hover / active states | Distinct `:hover` and `:active` colours per button, plus `:focus-visible` rings; transitions are 160 ms |
| No obvious functional errors | Type and 5 MB size validation with an inline message (`role="status"`, `aria-live="polite"`) instead of `alert()` |
| Responsive: side-by-side → stacked | Single breakpoint at 900 px; buttons stack again below 480 px |
| Show the uploaded file name | `file-name` element shows `✓ name · size`, and the dropzone switches to a filled state |

Extra: drag-and-drop with a depth counter (otherwise the highlight flickers as the cursor crosses
child elements), and a `drop` handler on `window` so a missed drop does not navigate away.

## Notes on fidelity

- The **illustration is redrawn as inline SVG** (cat, phone, two chat bubbles, quill). The original
  is a raster/hand-drawn asset that is not extractable from the shared frame, so it is reproduced
  as vector shapes in the same palette rather than substituted with a stock image. It is marked
  `aria-hidden` — it carries no information.
- The **webfont is the system stack**, not the frame's proprietary face; metrics are close but not
  identical. A one-line `@font-face` swap would close the gap.
- The **avatar/logo area is absent from the frame** and therefore absent here — nothing was invented.
- Spacing uses `clamp()` on the outer padding so the composition holds at 1440 px and at 1024 px
  without a second breakpoint.

## Accessibility

Semantic landmarks (`main` / `section` / `h1` / `h2`), a real `<input type="file">` behind the
label, visible focus rings, `aria-current="step"` on the active dot, `prefers-reduced-motion`
respected for the bubble float animation, and no colour-only state (the filled dropzone also
changes border style and shows the file name).
