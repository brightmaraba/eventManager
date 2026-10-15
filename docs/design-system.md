# Design system

Staff pages and the public seating page share [core/static/app.css](../core/static/app.css). Email templates stay plain. Print uses [reports/static/reports/print.css](../reports/static/reports/print.css).

## Tokens

| Token | Value | Use |
|---|---|---|
| `--olive` | `#283113` | Text, borders, focus ring |
| `--lime` | `#F3FF74` | Primary button fill, with olive text |
| `--ivory` | `#F5F4ED` | Page background and solid panels |
| `--danger` | `#8d2f2f` | Errors |

Lime is not used for body text or as the only focus indicator. Focus is a 3px olive outline.

Seat status colors live on the same tokens: `--seat-available`, `--seat-held`, `--seat-assigned`, `--seat-blocked`, and `--seat-checked-in`. The editor also writes the status in each seat name.

## Glass budget

Only three regions use `backdrop-filter`:

1. `.site-header.glass` on every page
2. `.metrics.glass` on the event detail summary
3. `.toolbar.glass` on the layout editor

Tables, ticket lists, dense forms, the room canvas, and check-in results stay solid. A page must not add another `.glass` region. Tests count ` glass` in the HTML and fail above three.

When `backdrop-filter` is unsupported, or the user prefers reduced transparency or forced colors, those regions become solid ivory (or the system canvas color) with a border and no blur. Reduced motion removes animation and transitions.

## Components

- `.panel` is a solid ivory surface for forms and navigation groups.
- `.status` is a solid notice. `.error` and `.errorlist` use the danger color.
- `button` and `.button` are lime with olive text. `.secondary` is an ivory button with an olive border.
- `.control`, inputs, selects, and textareas are full width except checkboxes, radios, and file inputs.
- Tables are full width with wrapping cells. At 320 CSS pixels, ordinary pages must not grow wider than the viewport. The room canvas stays desktop and tablet first; the keyboard forms under it are the small-screen path.

## Print

A4 and A3 output uses olive `#283113` on ivory `#F5F4ED`, solid cards, and wrapping text. Print CSS has no blur and no full-bleed lime. PDF generation attaches that stylesheet directly.
