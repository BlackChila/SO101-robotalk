# Third-party materials and attribution review

This inventory preserves the source project's license review dated 2026-10-09,
with removed FLUX/Galaxea integrations omitted. It is not a new review of all
dependencies in the conversation-focused repository, or a compatibility certification.
It does not grant rights to upstream code, checkpoints, voices, or API services.
Review the actual licenses at the pinned revisions used by your installation;
model terms may differ from their runtime library's license.

The maintainer confirmed sole authorship of the original project code, no copied
project code, and no employer/university obligations. The third-party components
below are installed/downloaded dependencies or external services; original
authorship does not remove their separate terms.

| Component | Upstream / provenance | Where RoboTalk records it |
| --- | --- | --- |
| LeRobot | [Hugging Face LeRobot](https://github.com/huggingface/lerobot/tree/73ab890324b303424a8a5f07272f22c36be5d269) | Shared robot runtime; external Molmo environment is separate |
| MolmoAct2 | [converted checkpoint](https://huggingface.co/lerobot/MolmoAct2-SO100_101-LeRobot), [original checkpoint](https://huggingface.co/allenai/MolmoAct2-SO100_101) | `environments/molmoact2/README.md` |
| Qwen ASR/TTS | [Qwen3-ASR](https://github.com/QwenLM/Qwen3-ASR), [Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS) | `environments/asr/` and `environments/tts/` manifests and locks |
| Dialogue GGUF | [ggml-org Qwen3.8-27B](https://huggingface.co/ggml-org/Qwen3.8-27B-GGUF) | `scripts/download_conversation.py`; local manifest generated on download |
| Piper and voices | [Piper](https://github.com/OHF-Voice/piper1-gpl), [voice collection](https://huggingface.co/rhasspy/piper-voices) | `environments/piper/`; check each voice's model card separately |
| OpenCV YuNet | [OpenCV Zoo face detector](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet) | `scripts/download_face_detector.py` pins size and SHA-256 |
| NATTEN and PyTorch/CUDA packages | [NATTEN](https://github.com/SHI-Labs/NATTEN), [PyTorch](https://pytorch.org/) | Environment locks and explicit wheel sources |
| Vite and npm dependencies | [Vite](https://github.com/vitejs/vite) | `ui/package.json` / `ui/package-lock.json` |
| LM Studio / OpenAI | [LM Studio](https://lmstudio.ai/), [OpenAI](https://openai.com/) | Optional external runtime/services; their own terms apply |

Downloaded weights and upstream source checkouts are ignored rather than vendored.
That does not remove attribution obligations for any copied or adapted code;
review project scripts for derivation before publishing under the chosen license.
In particular, assess copyleft dependency obligations for the way you intend to
distribute the software; this inventory does not determine compatibility.

## Confirmed terms and remaining license gaps

The review read official metadata for 236 distinct Python package/version pairs
from the source project's environment snapshots. Source licenses
were checked separately where metadata was incomplete. Local Linux/CUDA wheels
were not installed or unpacked, so wheel-specific bundled notices still matter
if distributing an installed environment. Build-package metadata is also
recorded in [the dependency inventory](dependency-license-inventory.md).

| Component | Reviewed terms / source | Publication implication |
| --- | --- | --- |
| Pinned LeRobot | [Apache-2.0](https://github.com/huggingface/lerobot/blob/73ab890324b303424a8a5f07272f22c36be5d269/LICENSE) | Keep its license/notices for any redistributed upstream code. |
| MolmoAct2 | [Code: Apache-2.0](https://github.com/allenai/molmoact2/blob/main/LICENSE); [pinned checkpoint](https://huggingface.co/allenai/MolmoAct2-SO100_101/tree/152569fe57914d97be91055800035f54e250d009) | The pinned model card/API did not declare a checkpoint license or list a license file. The code license alone does not establish weight-redistribution rights; clarify upstream before redistributing weights or adapters. |
| Qwen3-ASR and CustomVoice | [ASR model card](https://huggingface.co/Qwen/Qwen3-ASR-1.7B/blob/7278e1e70fe206f11671096ffdd38061171dd6e5/README.md), [TTS model card](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice/blob/0c0e3051f131929182e2c023b9537f8b1c68adfe/README.md): Apache-2.0 | Their runtime package metadata also declares Apache-2.0; preserve upstream notices if redistributing. |
| Reference dialogue GGUF | [Apache-2.0 model card](https://huggingface.co/ggml-org/Qwen3.8-27B-GGUF) | The download helper is not pinned on a fresh clone; verify the license of the actual downloaded revision. |
| Piper 1.8.0 | [GPL-3.0-or-later package metadata](https://pypi.org/pypi/piper-tts/1.8.0/json), [GPL text](https://github.com/OHF-Voice/piper1-gpl/blob/main/COPYING) | Original Apache-2.0 worker code is compatible with GPLv3, but a distributed combined program must comply with GPL; see below. Voice terms are separate. |
| ONNX Runtime / NATTEN / YuNet | [ONNX Runtime: MIT](https://pypi.org/pypi/onnxruntime/1.30.0/json), [NATTEN: MIT](https://github.com/SHI-Labs/NATTEN/blob/v0.21.6/LICENSE), [YuNet: MIT](https://github.com/opencv/opencv_zoo/blob/main/models/face_detection_yunet/LICENSE) | Preserve copyright/license notices when distributing the relevant software/model. |
| PyTorch / torchvision | [PyTorch metadata](https://pypi.org/pypi/torch/2.11.0/json): BSD-3-Clause; [torchvision metadata](https://pypi.org/pypi/torchvision/0.26.0/json): BSD | Binary packages can include additional licensed components; retain their notices in a packaged distribution. |
| NVIDIA libraries | [CUDA EULA](https://docs.nvidia.com/cuda/eula/index.html) and package-specific terms | Several locked packages omit a license identifier in PyPI metadata; do not infer an open-source grant or redistribution rights from that omission. |
| LM Studio | [LM Studio terms](https://lmstudio.ai/terms) | Separately installed proprietary software; local execution does not mean its application is open source or redistributable with RoboTalk. |
| OpenAI | [OpenAI terms](https://openai.com/policies/) | Optional cloud service; its service terms are independent of the repository license. |

### Copyleft software and the Piper worker

Other declared licenses include GPL for `pyyaml-include` and `soynlp`; LGPL for
`frozendict`, `pynput`, `python-xlib`, and `soxr`; MPL for `certifi` and part of
`orjson`. These are not all directly imported by RoboTalk, and the obligations
depend on the component and distribution. Permissive packages such as NumPy and
SciPy can also carry bundled third-party licenses in their binary distributions.

`scripts/piper_tts_worker.py` directly imports `PiperVoice` from GPL-covered Piper.
The [GNU FAQ on interpreted library bindings](https://www.gnu.org/licenses/gpl-faq.html#IfInterpreterIsGPL)
explains why using a GPL library can require the calling program to be distributed
under compatible terms. The original worker is now covered by the project's
[Apache-2.0 license](../LICENSE), which is
[compatible with GPLv3](https://apache.org/licenses/GPL-compatibility.html).
No separate GPL license exception was applied to its original source. This
does not turn Piper into Apache-licensed software: distribution of a combined
worker/Piper program must comply with GPL, including applicable notices and
corresponding-source requirements.

Keeping dependencies out of Git does not cancel those obligations. See
[the publication review](publication-review.md#ownership-and-project-license).

### Piper voices and dataset notices

The linked cards state **dataset** terms; they are not a complete legal analysis
of each model's fine-tuning lineage or generated audio. In particular, do not
automatically apply a dataset's ShareAlike terms to every generated clip.
The voices are downloaded locally, not shipped in this repository.

| Voice | Upstream card / stated dataset terms | Remaining point |
| --- | --- | --- |
| [Thorsten](https://huggingface.co/rhasspy/piper-voices/blob/main/de/de_DE/thorsten/medium/MODEL_CARD) | CC0 | Card says fine-tuned from Lessac; retain/review the actual voice-model notices. |
| [Kerstin](https://huggingface.co/rhasspy/piper-voices/blob/main/de/de_DE/kerstin/low/MODEL_CARD) | CC0 | Card says fine-tuned from Ryan (low); retain/review the actual voice-model notices. |
| [Amy](https://huggingface.co/rhasspy/piper-voices/blob/main/en/en_US/amy/medium/MODEL_CARD) | Refers to Mimic3 rather than naming a license | Exact dataset/model permission remains unresolved. |
| [Ryan](https://huggingface.co/rhasspy/piper-voices/blob/main/en/en_US/ryan/medium/MODEL_CARD) | CC BY-NC-SA 4.0 | Noncommercial/attribution/ShareAlike terms differ from the project's Apache-2.0 license. |
| [Alan](https://huggingface.co/rhasspy/piper-voices/blob/main/en/en_GB/alan/medium/MODEL_CARD) | Refers to Mimic3's `apope_low` | The linked [Mimic3 license](https://github.com/MycroftAI/mimic3-voices/blob/master/voices/en_UK/apope_low/LICENSE) states all rights reserved; redistribution permission was not established. |
| [Jenny (Dioco)](https://huggingface.co/rhasspy/piper-voices/blob/main/en/en_GB/jenny_dioco/medium/MODEL_CARD) | Refers to the [Dioco Jenny dataset](https://github.com/dioco-group/jenny-tts-dataset) | Dataset requests the name Jenny, preferably Jenny (Dioco), in interactive applications; it permits commercial use and does not require attribution on distributed audio clips. |

## Bundled assets requiring ownership confirmation

| Asset | What is distributed | Publication question |
| --- | --- | --- |
| Versioned `assets/demo/intro/audio-*.mp3` | Recorded/synthesized intro speech | Who created the audio and text, which voice terms apply, and is redistribution permitted? |
| `assets/demo/intro/*.jsonl` and `active.json` | Robot-specific recorded gesture and calibration fingerprint | Is public distribution intentional, and are any contributor permissions needed? |

Original project code and documentation use [Apache-2.0](../LICENSE), as scoped
in the [README](../README.md#contributing-and-licensing). Third-party material
retains its own terms. The bundled `assets/demo/` material above
is excluded from the project license until ownership and redistribution rights
are confirmed. Exclusion does not itself establish permission to publish it.

Once ownership and terms are established, add the required notices and update
the scope explicitly. Track remaining decisions in
[the publication checklist](publishing-checklist.md).
