# Conversation UI previews

Both screenshots are rendered from the current English application at a
1440 × 1000 CSS-pixel viewport and device pixel ratio 1:

| Screenshot | App state |
| --- | --- |
| `conversation-home.png` | Settings closed: the focused conversation homepage. Camera previews are hidden by the application in this state. |
| `conversation-camera-preview.png` | Settings open: conversation controls, settings panel, overhead camera and Insta360 X5 side view. |

The renderer uses the application HTML, JavaScript and CSS unchanged, with
simulated backend responses. The settings view includes two archived camera
captures. These are illustrative previews, not live hardware-session screenshots.
The settings gear and the panel's close control were used normally between
captures; no CSS or DOM layout overrides were applied. Geometry for both states
is recorded in `layout-measurements.json`.

## Camera source and edits

Source: the original project's archived
`ui/design/settings-color-variants-2026-10-16/references/control.png` at source
commit `3685039c5575686666af826a68675e25075a1071` (1265 × 712 pixels).

The screenshot clips the camera panels at its bottom edge. The available image
areas were cropped to 4:3 without including the old UI controls:

| View | Source rectangle (left, top, right, bottom) | Crop size |
| --- | --- | --- |
| Overhead | `(350, 442, 710, 712)` | 360 × 270 |
| Side / Insta360 X5 | `(790, 442, 1150, 712)` | 360 × 270 |

The built-in Image Generation tool removed the loose black cable from both
camera captures. This was an editorial image edit, not a change to camera
processing or robot behavior. Prompts are recorded in `imagegen-prompts.json`.
Edited outputs were resized to 720 × 540 JPEGs under `camera-previews/` and fed
through the app's normal `conversation` camera-preview response.

The camera frame positions, dimensions, aspect ratios, labels, overlays and
settings panel come from `ui/src/conversation-redesign.css` and `ui/src/main.js`.
No CSS or DOM layout overrides were used. No Wrist capture was supplied; the
application hides that view using its normal missing-camera behavior.
