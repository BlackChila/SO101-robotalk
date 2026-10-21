---
name: RoboTalk Gespräch
description: Minimal conversation workspace with a persistent settings inspector
colors:
  primary: "#436a57"
  primary-hover: "#345442"
  voice-heading: "#2d713c"
  ink: "#162d29"
  muted: "#586d65"
  surface: "#fcfdfb"
  surface-soft: "#f5f8f5"
  line: "#d9e4dd"
  speech-orb: "#d2e4c4"
  waveform: "#9ab5a4"
typography:
  headline:
    fontFamily: "Inter, ui-sans-serif, sans-serif"
    fontSize: "32px"
    fontWeight: 650
    lineHeight: 1.25
    letterSpacing: "-0.03em"
  label:
    fontFamily: "Inter, ui-sans-serif, sans-serif"
    fontSize: "13px"
    fontWeight: 500
    lineHeight: 1.5
rounded:
  control: "5px"
  panel: "6px"
spacing:
  small: "12px"
  medium: "16px"
  group: "24px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "#ffffff"
    rounded: "{rounded.panel}"
    padding: "12px 22px"
  button-primary-hover:
    backgroundColor: "{colors.primary-hover}"
---

# RoboTalk Gespräch

## Overview

The user-approved Graphit × Cybergrün concept remains the conversation workspace's visual reference. Keep it quiet, readable and usable with settings expanded. Conversation is the sole homepage, with a settings control and no tab navigation. Preserve conversation functionality and the green action palette in theme.css.

## Colors

The settings inspector uses the user-selected pale green #f5f8f3. Text is #23362a, secondary controls #fcfdfb, hover #eaf0e6, disabled fills #edf1ea and separators #dce5d7. Scope these roles to the inspector so the main canvas stays unchanged. Primary actions retain Cybergrün #436a57.

Muted rich green carries primary actions and selected mode. The green voice name in the heading is the voice selector itself. Popup choices are black on light surfaces, with white text on the green selected row. Actual loading/error/disabled states remain distinguishable; camera pixels are real previews, never generated placeholders in the running app.

## Typography

Use the existing Inter/system sans stack. A 32px desktop heading steps to 28px on narrower layouts. Labels and feedback remain compact and readable, with tabular camera values.

## Layout

At desktop widths: broad conversation/camera workspace plus a 370px settings inspector. The main stage places identity/voice selection beside waveform and call action. The filmstrip contains exactly three views: Overhead, Insta360 and Wrist-Kamera. The Wrist slot shows its ordinary live image when idle and the upright marked tracking image during tracking. All three image frames share one height; the portrait Wrist column is narrower (16:16:9 column proportions). Open camera settings span the row below all previews. At 1180px, reduce inspector width and stack stage content; at 860px, place the inspector below the workspace; at 560px, stack the three cameras and camera settings without horizontal scrolling.

With settings closed, use a single centered conversation composition rather than the inspector workspace's split stage: heading with inline voice selection, output waveform, primary action and feedback in one vertical group. The container is at most 640px wide; the action at most 304px. Use 32px group spacing and optical vertical centering within the remaining viewport, accounting for the 70px desktop or 112px mobile header. Heading sizes step from 36px to 32px to 28px. Hide the empty task label/divider only in this focused state; reveal the complete existing status area as soon as actual task feedback is present. Long messages may extend the page naturally.

## Elevation & Depth

Use thin green-gray separators and tonal surfaces for the workspace. The user explicitly requested the original soft, shaded circular speech visualization with concentric rings. Retain its original gradient and inset depth. Listening/thinking use the original subtle breathing animation. Actual playback amplitude scales the core up to 20% and the halo up to 10%, with 45ms attack and 130ms release. Speaking uses this measured envelope rather than an artificial speaking loop. Silence returns to resting size; reduced-motion preferences disable breathing and scaling.

Show that circle only with settings closed. With settings open, replace it with the horizontal amplitude bars. Their container shares the call button's maximum width of 370px and shrinks with the available space, so the bars never extend beyond the button. Both renderings inherit the same playback level; toggling settings changes presentation without restarting audio or analysis. The bars return to a 4px baseline during silence and stay still under reduced motion.

## Shapes

Small 5–6px radii for controls and sections. The heading's voice selector is unboxed, with only its dropdown indicator beside the green name. The real tracking image is contained in the portrait Wrist frame without stretching, cropping or a second rotation. The raw Wrist live image remains the idle fallback and is displayed 90 degrees clockwise, matching tracking's upright orientation. There is no separate tracking placeholder or fourth view. The original Wrist settings button stays available in the same frame.

## Components

- The voice menu is integrated directly in the heading name. Its native keyboard interaction and wheel gestures use one VoicePicker and the existing selectConversationSpeaker boundary. Keep mode-specific options, stored selection and Realtime locks. Keep the selector free of a visible helper tooltip; retain its accessible name and screen-reader description.
- The opened voice menu uses the conversation green for the selected option, light green for hover/focus, and a green scrollbar. Use the native customizable select picker where supported, retaining native keyboard and accessibility behavior. The closed control is the green name directly in the heading.
- Directly below the three voice modes, show a two-segment `Gesprächssprache` fieldset: `Deutsch` and `English`. Reuse the same segmented control styling and selected green, with a short note that it applies to the next call including its greeting. Lock it with the mode selector while a call or transition is active.
- Robot reset spans the inspector width. Directly below it, `Model Run stoppen` and model unload share one row with equal widths and heights and a 10px gap. Torque actions follow. Reset semantics remain accessible through the heading info button and an action description. The run-stop button is enabled only for an active MolmoAct2 task; it stops the task while preserving the loaded model and voice connection.
- Use the existing `.help-tip` info buttons beside the existing Suchstart and Roboter headings, without adding Modell or Drehmoment headings. German explanations appear on hover, focus or click; Escape and outside clicks dismiss them. The Roboter tip explains reset, run stop, unload and both torque actions. Keep accessible descriptions on action buttons without native title tooltips. Run-stop and unload stay side by side. Contain popovers within the inspector and place the Roboter tip above its trigger.
- Keep one set of camera, camera-status/profile/reload and torque controls in the conversation workspace. Do not duplicate handlers or create another camera owner.
- Keep the existing model-unload button and endpoint. Place it next to `Model Run stoppen`, with matching width and height; keep it visible but disabled if no policy is loaded. Unload preserves voice, cameras and the holder. Show progress, success and errors in the visible conversation task-feedback area.
- Preserve independent brightness, supported exposure and projection apply/default actions. Keep live feedback and errors. The user removed the research/sources section and placeholder from the UI; web search remains a conversation tool without a visible results panel.

## Do's and Don'ts

- Do retain every original controller gate and lifecycle behavior.
- Do show truthful empty, disabled and error states.
- Do preserve portrait tracking and the green inline heading selector.
- Do keep the existing conversation action-button palette.
- Don't treat frontend/browser verification as physical acceptance.
