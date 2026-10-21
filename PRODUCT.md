# RoboTalk

<!-- impeccable:product-schema 1 -->

## Platform

web

## Product Purpose

Browser interface for spoken conversation with a physical SO-101 and optional MolmoAct2 manipulation. English interface labels; Conversation is the sole homepage with no tab selector. Product facts are defined in README.md and ui/README.md.

## Operating Context

The reference deployment is a local Linux ARM64 workstation. A Vite frontend is served by the existing Python backend. Hardware-free conversation is possible when the configured Follower device is absent. Starting a conversation with the arm connected can initiate positioning, intro gestures and subsequent robot actions.

## Capabilities and Constraints

- Conversation supports ChatGPT Realtime, local Qwen and local Piper, mode-specific voice lists, camera previews, face tracking, robot reset, explicit torque actions, shared policy-model unload and web-search sources. `Stop model run` stops an active MolmoAct2 task without unloading the model or ending voice; conversation end and robot reset also retain their task-stop handling.
- Conversation language is explicitly selectable as German or English directly below the voice modes. It applies from the initial model-generated greeting and is remembered for the next call. All three modes use it for prompts; local recognition/synthesis follow it too. Piper offers matching language-specific voices.
- Research and sources are not exposed as a UI section. Realtime search remains available to the conversation, with results passed to the model rather than a visible panel.
- Preserve every existing function, controller gate, status, error and return/recovery path when changing the interface.
- Wrist is always shown upright in portrait orientation. Rotate raw frames 90 degrees clockwise; tracking previews are already rotated and must retain their natural portrait aspect ratio.
- Conversation shows three camera slots with equal image-frame heights. Wrist camera shows the raw Wrist stream when idle and the marked tracking preview during tracking, in the same slot with its original settings control.
- Voice selection lives directly in the green heading name, with a dropdown indicator, keyboard and the existing wheel interaction. The separate picker bar and previous/next buttons were removed at the user's request. Realtime voice changes remain locked during active/returning/preparing conversations.
- Software stop/disconnect behavior and hardware authorization follow AGENTS.md. A visual redesign does not authorize physical acceptance tests.

## Brand Commitments

The user explicitly selected #f5f8f3 for the settings inspector background in Conversation, with matching pale secondary control fills and separators. The main workspace stays light; Cybergrün remains the action color.

The user approved the Graphit layout with the richer green/sage palette, called Cybergrün in the conversation. The selected voice name is green in the Conversation heading and is itself the voice-menu control. The voice selector has no visible helper tooltip. Menu choices use readable black text, with a green selected row.

## Evidence on Hand

The implemented conversation styles in ui/src/conversation-redesign.css and ui/src/theme.css preserve the approved Graphit × Cybergrün design. Historical generated design explorations are omitted from the new repository; live camera previews remain actual camera images.
