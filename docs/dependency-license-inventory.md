# Dependency license metadata — inherited 2026-10-09 review

This appendix retains the source project's recorded registry metadata for ASR,
conversation and Qwen TTS environments, plus frontend dependencies. Rows exclusive
to the removed FLUX/Galaxea environments are omitted. This is historical metadata,
not a fresh audit of the new robot runtime, Piper or an externally prepared
MolmoAct2 environment. Review actual package/wheel notices before distribution.

See [third-party materials](third-party-materials.md) for model/voice provenance,
Piper distribution requirements and remaining permissions questions. The original
source's full inventory remains in its Git history.

## Python package metadata


| Package / version | Environment snapshots | Declared license metadata |
| --- | --- | --- |
| [accelerate 1.12.0](https://pypi.org/pypi/accelerate/1.12.0/json) | asr, tts | Apache |
| [accelerate 1.15.0](https://pypi.org/pypi/accelerate/1.15.0/json) | conversation | Apache |
| [annotated-doc 0.0.5](https://pypi.org/pypi/annotated-doc/0.0.5/json) | asr, conversation, tts | MIT |
| [annotated-types 0.8.0](https://pypi.org/pypi/annotated-types/0.8.0/json) | asr, tts | MIT |
| [anyio 4.15.1](https://pypi.org/pypi/anyio/4.15.1/json) | asr, conversation, tts | MIT |
| [av 18.1.0](https://pypi.org/pypi/av/18.1.0/json) | asr | BSD-3-Clause |
| [blinker 1.9.0](https://pypi.org/pypi/blinker/1.9.0/json) | asr | MIT License |
| [brotli 1.2.0](https://pypi.org/pypi/brotli/1.2.0/json) | asr, tts | MIT |
| [certifi 2026.7.22](https://pypi.org/pypi/certifi/2026.7.22/json) | asr, conversation, tts | MPL-2.0 |
| [cffi 2.1.1](https://pypi.org/pypi/cffi/2.1.1/json) | asr, tts | MIT-0 |
| [charset-normalizer 3.5.1](https://pypi.org/pypi/charset-normalizer/3.5.1/json) | asr, tts | MIT |
| [click 8.5.0](https://pypi.org/pypi/click/8.5.0/json) | asr, conversation, tts | BSD-3-Clause |
| [cloudpickle 3.1.2](https://pypi.org/pypi/cloudpickle/3.1.2/json) | asr, tts | BSD-3-Clause |
| [cuda-bindings 13.4.3](https://pypi.org/pypi/cuda-bindings/13.4.3/json) | asr, conversation, tts | Apache-2.0 |
| [cuda-pathfinder 1.8.2](https://pypi.org/pypi/cuda-pathfinder/1.8.2/json) | asr, conversation, tts | Apache-2.0 |
| [cuda-toolkit 13.0.2](https://pypi.org/pypi/cuda-toolkit/13.0.2/json) | asr, conversation, tts | Not declared / unavailable in queried metadata |
| [cython 3.3.0](https://pypi.org/pypi/cython/3.3.0/json) | asr | Apache-2.0 |
| [decorator 5.3.1](https://pypi.org/pypi/decorator/5.3.1/json) | asr, tts | BSD-2-Clause |
| [dynet38 2.2](https://pypi.org/pypi/dynet38/2.2/json) | asr | Apache 2.0 |
| [einops 0.8.2](https://pypi.org/pypi/einops/0.8.2/json) | tts | MIT |
| [fastapi 0.141.1](https://pypi.org/pypi/fastapi/0.141.1/json) | asr, tts | MIT |
| [filelock 4.0.3](https://pypi.org/pypi/filelock/4.0.3/json) | asr, conversation, tts | MIT |
| [flask 3.1.3](https://pypi.org/pypi/flask/3.1.3/json) | asr | BSD-3-Clause |
| [flatbuffers 25.12.19](https://pypi.org/pypi/flatbuffers/25.12.19/json) | piper, tts | Apache 2.0 |
| [fsspec 2026.9.0](https://pypi.org/pypi/fsspec/2026.9.0/json) | asr, conversation, tts | BSD-3-Clause |
| [gradio 6.17.3](https://pypi.org/pypi/gradio/6.17.3/json) | asr, tts | Apache-2.0 |
| [gradio-client 2.5.0](https://pypi.org/pypi/gradio-client/2.5.0/json) | asr, tts | Apache-2.0 |
| [groovy 0.1.2](https://pypi.org/pypi/groovy/0.1.2/json) | asr, tts | MIT License |
| [h11 0.16.0](https://pypi.org/pypi/h11/0.16.0/json) | asr, conversation, tts | MIT |
| [hf-gradio 0.4.1](https://pypi.org/pypi/hf-gradio/0.4.1/json) | asr, tts | MIT |
| [hf-xet 1.6.0](https://pypi.org/pypi/hf-xet/1.6.0/json) | asr, conversation, tts | Apache-2.0 |
| [httpcore 1.0.9](https://pypi.org/pypi/httpcore/1.0.9/json) | asr, conversation, tts | BSD-3-Clause |
| [httpx 0.28.1](https://pypi.org/pypi/httpx/0.28.1/json) | asr, conversation, tts | BSD-3-Clause |
| [huggingface-hub 0.36.2](https://pypi.org/pypi/huggingface-hub/0.36.2/json) | asr, tts | Apache |
| [huggingface-hub 1.33.0](https://pypi.org/pypi/huggingface-hub/1.33.0/json) | conversation | Apache-2.0 |
| [idna 3.20](https://pypi.org/pypi/idna/3.20/json) | asr, conversation, tts | BSD-3-Clause |
| [itsdangerous 2.2.0](https://pypi.org/pypi/itsdangerous/2.2.0/json) | asr | BSD License |
| [jinja2 3.1.6](https://pypi.org/pypi/jinja2/3.1.6/json) | asr, conversation, tts | BSD License |
| [joblib 1.6.0](https://pypi.org/pypi/joblib/1.6.0/json) | asr, tts | BSD-3-Clause |
| [lazy-loader 0.6](https://pypi.org/pypi/lazy-loader/0.6/json) | asr, tts | BSD-3-Clause |
| [librosa 1.0.0](https://pypi.org/pypi/librosa/1.0.0/json) | asr, tts | ISC |
| [llvmlite 0.49.0](https://pypi.org/pypi/llvmlite/0.49.0/json) | asr, tts | BSD-2-Clause AND Apache-2.0 WITH LLVM-exception |
| [markdown-it-py 4.2.0](https://pypi.org/pypi/markdown-it-py/4.2.0/json) | asr, conversation, tts | MIT License |
| [markupsafe 3.0.3](https://pypi.org/pypi/markupsafe/3.0.3/json) | asr, conversation, tts | BSD-3-Clause |
| [mdurl 0.1.2](https://pypi.org/pypi/mdurl/0.1.2/json) | asr, conversation, tts | MIT License |
| [mpmath 1.3.0](https://pypi.org/pypi/mpmath/1.3.0/json) | asr, conversation, tts | BSD |
| [msgpack 1.2.2](https://pypi.org/pypi/msgpack/1.2.2/json) | asr, tts | Apache-2.0 |
| [nagisa 0.2.11](https://pypi.org/pypi/nagisa/0.2.11/json) | asr | MIT License |
| [narwhals 2.26.0](https://pypi.org/pypi/narwhals/2.26.0/json) | asr, tts | MIT |
| [networkx 3.7](https://pypi.org/pypi/networkx/3.7/json) | asr, conversation, tts | BSD-3-Clause |
| [numba 0.67.0](https://pypi.org/pypi/numba/0.67.0/json) | asr, tts | BSD |
| [numpy 2.5.3](https://pypi.org/pypi/numpy/2.5.3/json) | asr, conversation, piper, tts | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 |
| [nvidia-cublas 13.1.0.3](https://pypi.org/pypi/nvidia-cublas/13.1.0.3/json) | asr, conversation, tts | Not declared / unavailable in queried metadata |
| [nvidia-cuda-cupti 13.0.85](https://pypi.org/pypi/nvidia-cuda-cupti/13.0.85/json) | asr, conversation, tts | LicenseRef-NVIDIA-Proprietary |
| [nvidia-cuda-nvrtc 13.0.88](https://pypi.org/pypi/nvidia-cuda-nvrtc/13.0.88/json) | asr, conversation, tts | LicenseRef-NVIDIA-Proprietary |
| [nvidia-cuda-runtime 13.0.96](https://pypi.org/pypi/nvidia-cuda-runtime/13.0.96/json) | asr, conversation, tts | Not declared / unavailable in queried metadata |
| [nvidia-cudnn-cu13 9.19.0.56](https://pypi.org/pypi/nvidia-cudnn-cu13/9.19.0.56/json) | asr, conversation, tts | Not declared / unavailable in queried metadata |
| [nvidia-cufft 12.0.0.61](https://pypi.org/pypi/nvidia-cufft/12.0.0.61/json) | asr, conversation, tts | LicenseRef-NVIDIA-Proprietary |
| [nvidia-cufile 1.15.1.6](https://pypi.org/pypi/nvidia-cufile/1.15.1.6/json) | asr, conversation, tts | LicenseRef-NVIDIA-Proprietary |
| [nvidia-curand 10.4.0.35](https://pypi.org/pypi/nvidia-curand/10.4.0.35/json) | asr, conversation, tts | LicenseRef-NVIDIA-Proprietary |
| [nvidia-cusolver 12.0.4.66](https://pypi.org/pypi/nvidia-cusolver/12.0.4.66/json) | asr, conversation, tts | LicenseRef-NVIDIA-Proprietary |
| [nvidia-cusparse 12.6.3.3](https://pypi.org/pypi/nvidia-cusparse/12.6.3.3/json) | asr, conversation, tts | LicenseRef-NVIDIA-Proprietary |
| [nvidia-cusparselt-cu13 0.8.0](https://pypi.org/pypi/nvidia-cusparselt-cu13/0.8.0/json) | asr, conversation, tts | NVIDIA Proprietary Software |
| [nvidia-nccl-cu13 2.28.9](https://pypi.org/pypi/nvidia-nccl-cu13/2.28.9/json) | asr, conversation, tts | Not declared / unavailable in queried metadata |
| [nvidia-nvjitlink 13.0.88](https://pypi.org/pypi/nvidia-nvjitlink/13.0.88/json) | asr, conversation, tts | LicenseRef-NVIDIA-Proprietary |
| [nvidia-nvshmem-cu13 3.4.5](https://pypi.org/pypi/nvidia-nvshmem-cu13/3.4.5/json) | asr, conversation, tts | Not declared / unavailable in queried metadata |
| [nvidia-nvtx 13.0.85](https://pypi.org/pypi/nvidia-nvtx/13.0.85/json) | asr, conversation, tts | Apache 2.0 |
| [onnxruntime 1.30.0](https://pypi.org/pypi/onnxruntime/1.30.0/json) | piper, tts | MIT License |
| [orjson 3.12.0](https://pypi.org/pypi/orjson/3.12.0/json) | asr, tts | MPL-2.0 AND (Apache-2.0 OR MIT) |
| [packaging 26.3](https://pypi.org/pypi/packaging/26.3/json) | asr, conversation, piper, tts | Apache-2.0 OR BSD-2-Clause |
| [pandas 3.0.6](https://pypi.org/pypi/pandas/3.0.6/json) | asr, tts | BSD License |
| [pathvalidate 3.3.1](https://pypi.org/pypi/pathvalidate/3.3.1/json) | piper | MIT License |
| [pillow 12.3.0](https://pypi.org/pypi/pillow/12.3.0/json) | asr, conversation, tts | MIT-CMU |
| [piper-tts 1.8.0](https://pypi.org/pypi/piper-tts/1.8.0/json) | piper | GPL-3.0-or-later |
| [platformdirs 4.11.12](https://pypi.org/pypi/platformdirs/4.11.12/json) | asr, tts | MIT |
| [pooch 1.9.0](https://pypi.org/pypi/pooch/1.9.0/json) | asr, tts | BSD-3-Clause |
| [protobuf 7.36.2](https://pypi.org/pypi/protobuf/7.36.2/json) | piper, tts | 3-Clause BSD License |
| [psutil 7.2.2](https://pypi.org/pypi/psutil/7.2.2/json) | asr, conversation, tts | BSD-3-Clause |
| [pycparser 3.0](https://pypi.org/pypi/pycparser/3.0/json) | asr, tts | BSD-3-Clause |
| [pydantic 2.13.5](https://pypi.org/pypi/pydantic/2.13.5/json) | asr, tts | MIT |
| [pydantic-core 2.46.5](https://pypi.org/pypi/pydantic-core/2.46.5/json) | asr, tts | MIT |
| [pydub 0.25.1](https://pypi.org/pypi/pydub/0.25.1/json) | asr, tts | MIT |
| [pygments 2.21.0](https://pypi.org/pypi/pygments/2.21.0/json) | asr, conversation, tts | BSD-2-Clause |
| [python-dateutil 2.9.0.post0](https://pypi.org/pypi/python-dateutil/2.9.0.post0/json) | asr, tts | Dual License |
| [python-multipart 0.0.32](https://pypi.org/pypi/python-multipart/0.0.32/json) | asr, tts | Apache-2.0 |
| [pytz 2026.4](https://pypi.org/pypi/pytz/2026.4/json) | asr, tts | MIT |
| [pyyaml 6.0.3](https://pypi.org/pypi/pyyaml/6.0.3/json) | asr, conversation, tts | MIT |
| [qwen-asr 0.0.6](https://pypi.org/pypi/qwen-asr/0.0.6/json) | asr | Apache-2.0 |
| [qwen-omni-utils 0.0.9](https://pypi.org/pypi/qwen-omni-utils/0.0.9/json) | asr | Apache-2.0 |
| [qwen-tts 0.1.1](https://pypi.org/pypi/qwen-tts/0.1.1/json) | tts | Apache-2.0 |
| [regex 2026.9.10](https://pypi.org/pypi/regex/2026.9.10/json) | asr, conversation, tts | Apache-2.0 AND CNRI-Python |
| [requests 2.34.2](https://pypi.org/pypi/requests/2.34.2/json) | asr, tts | Apache-2.0 |
| [rich 15.0.0](https://pypi.org/pypi/rich/15.0.0/json) | asr, conversation, tts | MIT |
| [safehttpx 0.1.7](https://pypi.org/pypi/safehttpx/0.1.7/json) | asr, tts | MIT License |
| [safetensors 0.8.0](https://pypi.org/pypi/safetensors/0.8.0/json) | asr, conversation, tts | Apache Software License |
| [scikit-learn 1.9.1](https://pypi.org/pypi/scikit-learn/1.9.1/json) | asr, tts | BSD-3-Clause |
| [scipy 1.18.1](https://pypi.org/pypi/scipy/1.18.1/json) | asr, tts | BSD License |
| [semantic-version 2.10.0](https://pypi.org/pypi/semantic-version/2.10.0/json) | asr, tts | BSD |
| [setuptools 81.0.0](https://pypi.org/pypi/setuptools/81.0.0/json) | asr, conversation, tts | MIT |
| [shellingham 1.5.4](https://pypi.org/pypi/shellingham/1.5.4/json) | asr, conversation, tts | ISC License |
| [six 1.17.0](https://pypi.org/pypi/six/1.17.0/json) | asr, tts | MIT |
| [soundfile 0.14.0](https://pypi.org/pypi/soundfile/0.14.0/json) | asr, tts | BSD 3-Clause License |
| [sox 1.5.0](https://pypi.org/pypi/sox/1.5.0/json) | asr, tts | BSD-3-Clause |
| [soxr 1.1.0](https://pypi.org/pypi/soxr/1.1.0/json) | asr, tts | LGPL-2.1-or-later |
| [soynlp 0.0.493](https://pypi.org/pypi/soynlp/0.0.493/json) | asr | GNU General Public License v3 (GPLv3) |
| [starlette 1.7.0](https://pypi.org/pypi/starlette/1.7.0/json) | asr, tts | BSD-3-Clause |
| [sympy 1.14.0](https://pypi.org/pypi/sympy/1.14.0/json) | asr, conversation, tts | BSD |
| [threadpoolctl 3.7.0](https://pypi.org/pypi/threadpoolctl/3.7.0/json) | asr, tts | BSD-3-Clause |
| [tokenizers 0.22.2](https://pypi.org/pypi/tokenizers/0.22.2/json) | asr, tts | Apache Software License |
| [tokenizers 0.23.2](https://pypi.org/pypi/tokenizers/0.23.2/json) | conversation | Apache Software License |
| [tomlkit 0.14.0](https://pypi.org/pypi/tomlkit/0.14.0/json) | asr, tts | MIT |
| [torch 2.11.0+cu130](https://pypi.org/pypi/torch/2.11.0/json) | asr, conversation, tts | BSD-3-Clause |
| [torchaudio 2.11.0](https://pypi.org/pypi/torchaudio/2.11.0/json) | tts | BSD License |
| [torchvision 0.26.0+cu130](https://pypi.org/pypi/torchvision/0.26.0/json) | conversation | BSD |
| [tqdm 4.70.1](https://pypi.org/pypi/tqdm/4.70.1/json) | asr, conversation, tts | MPL-2.0 AND MIT |
| [transformers 4.57.3](https://pypi.org/pypi/transformers/4.57.3/json) | tts | Apache 2.0 License |
| [transformers 4.57.6](https://pypi.org/pypi/transformers/4.57.6/json) | asr | Apache 2.0 License |
| [transformers 5.17.0](https://pypi.org/pypi/transformers/5.17.0/json) | conversation | Apache 2.0 License |
| [triton 3.6.0](https://pypi.org/pypi/triton/3.6.0/json) | asr, conversation, tts | MIT License |
| [typer 0.27.2](https://pypi.org/pypi/typer/0.27.2/json) | asr, conversation, tts | MIT |
| [typing-extensions 4.16.0](https://pypi.org/pypi/typing-extensions/4.16.0/json) | asr, conversation, tts | PSF-2.0 |
| [typing-inspection 0.4.4](https://pypi.org/pypi/typing-inspection/0.4.4/json) | asr, tts | MIT |
| [urllib3 2.8.0](https://pypi.org/pypi/urllib3/2.8.0/json) | asr, tts | MIT |
| [uvicorn 0.53.0](https://pypi.org/pypi/uvicorn/0.53.0/json) | asr, tts | BSD-3-Clause |
| [werkzeug 3.1.8](https://pypi.org/pypi/werkzeug/3.1.8/json) | asr | BSD-3-Clause |

## npm build-package metadata

Reviewed 58 locked package entries, including optional platform binaries; this does not imply all are installed on the Linux host.

| Package / version | Registry license declaration |
| --- | --- |
| [@esbuild/aix-ppc64 0.21.5](https://registry.npmjs.org/@esbuild%2Faix-ppc64/0.21.5) | MIT |
| [@esbuild/android-arm 0.21.5](https://registry.npmjs.org/@esbuild%2Fandroid-arm/0.21.5) | MIT |
| [@esbuild/android-arm64 0.21.5](https://registry.npmjs.org/@esbuild%2Fandroid-arm64/0.21.5) | MIT |
| [@esbuild/android-x64 0.21.5](https://registry.npmjs.org/@esbuild%2Fandroid-x64/0.21.5) | MIT |
| [@esbuild/darwin-arm64 0.21.5](https://registry.npmjs.org/@esbuild%2Fdarwin-arm64/0.21.5) | MIT |
| [@esbuild/darwin-x64 0.21.5](https://registry.npmjs.org/@esbuild%2Fdarwin-x64/0.21.5) | MIT |
| [@esbuild/freebsd-arm64 0.21.5](https://registry.npmjs.org/@esbuild%2Ffreebsd-arm64/0.21.5) | MIT |
| [@esbuild/freebsd-x64 0.21.5](https://registry.npmjs.org/@esbuild%2Ffreebsd-x64/0.21.5) | MIT |
| [@esbuild/linux-arm 0.21.5](https://registry.npmjs.org/@esbuild%2Flinux-arm/0.21.5) | MIT |
| [@esbuild/linux-arm64 0.21.5](https://registry.npmjs.org/@esbuild%2Flinux-arm64/0.21.5) | MIT |
| [@esbuild/linux-ia32 0.21.5](https://registry.npmjs.org/@esbuild%2Flinux-ia32/0.21.5) | MIT |
| [@esbuild/linux-loong64 0.21.5](https://registry.npmjs.org/@esbuild%2Flinux-loong64/0.21.5) | MIT |
| [@esbuild/linux-mips64el 0.21.5](https://registry.npmjs.org/@esbuild%2Flinux-mips64el/0.21.5) | MIT |
| [@esbuild/linux-ppc64 0.21.5](https://registry.npmjs.org/@esbuild%2Flinux-ppc64/0.21.5) | MIT |
| [@esbuild/linux-riscv64 0.21.5](https://registry.npmjs.org/@esbuild%2Flinux-riscv64/0.21.5) | MIT |
| [@esbuild/linux-s390x 0.21.5](https://registry.npmjs.org/@esbuild%2Flinux-s390x/0.21.5) | MIT |
| [@esbuild/linux-x64 0.21.5](https://registry.npmjs.org/@esbuild%2Flinux-x64/0.21.5) | MIT |
| [@esbuild/netbsd-x64 0.21.5](https://registry.npmjs.org/@esbuild%2Fnetbsd-x64/0.21.5) | MIT |
| [@esbuild/openbsd-x64 0.21.5](https://registry.npmjs.org/@esbuild%2Fopenbsd-x64/0.21.5) | MIT |
| [@esbuild/sunos-x64 0.21.5](https://registry.npmjs.org/@esbuild%2Fsunos-x64/0.21.5) | MIT |
| [@esbuild/win32-arm64 0.21.5](https://registry.npmjs.org/@esbuild%2Fwin32-arm64/0.21.5) | MIT |
| [@esbuild/win32-ia32 0.21.5](https://registry.npmjs.org/@esbuild%2Fwin32-ia32/0.21.5) | MIT |
| [@esbuild/win32-x64 0.21.5](https://registry.npmjs.org/@esbuild%2Fwin32-x64/0.21.5) | MIT |
| [@napi-rs/lzma-linux-x64-gnu 1.5.1](https://registry.npmjs.org/@napi-rs%2Flzma-linux-x64-gnu/1.5.1) | MIT |
| [@rollup/rollup-android-arm-eabi 4.63.5](https://registry.npmjs.org/@rollup%2Frollup-android-arm-eabi/4.63.5) | MIT |
| [@rollup/rollup-android-arm64 4.63.5](https://registry.npmjs.org/@rollup%2Frollup-android-arm64/4.63.5) | MIT |
| [@rollup/rollup-darwin-arm64 4.63.5](https://registry.npmjs.org/@rollup%2Frollup-darwin-arm64/4.63.5) | MIT |
| [@rollup/rollup-darwin-x64 4.63.5](https://registry.npmjs.org/@rollup%2Frollup-darwin-x64/4.63.5) | MIT |
| [@rollup/rollup-freebsd-arm64 4.63.5](https://registry.npmjs.org/@rollup%2Frollup-freebsd-arm64/4.63.5) | MIT |
| [@rollup/rollup-freebsd-x64 4.63.5](https://registry.npmjs.org/@rollup%2Frollup-freebsd-x64/4.63.5) | MIT |
| [@rollup/rollup-linux-arm-gnueabihf 4.63.5](https://registry.npmjs.org/@rollup%2Frollup-linux-arm-gnueabihf/4.63.5) | MIT |
| [@rollup/rollup-linux-arm-musleabihf 4.63.5](https://registry.npmjs.org/@rollup%2Frollup-linux-arm-musleabihf/4.63.5) | MIT |
| [@rollup/rollup-linux-arm64-gnu 4.63.5](https://registry.npmjs.org/@rollup%2Frollup-linux-arm64-gnu/4.63.5) | MIT |
| [@rollup/rollup-linux-arm64-musl 4.63.5](https://registry.npmjs.org/@rollup%2Frollup-linux-arm64-musl/4.63.5) | MIT |
| [@rollup/rollup-linux-loong64-gnu 4.63.5](https://registry.npmjs.org/@rollup%2Frollup-linux-loong64-gnu/4.63.5) | MIT |
| [@rollup/rollup-linux-loong64-musl 4.63.5](https://registry.npmjs.org/@rollup%2Frollup-linux-loong64-musl/4.63.5) | MIT |
| [@rollup/rollup-linux-ppc64-gnu 4.63.5](https://registry.npmjs.org/@rollup%2Frollup-linux-ppc64-gnu/4.63.5) | MIT |
| [@rollup/rollup-linux-ppc64-musl 4.63.5](https://registry.npmjs.org/@rollup%2Frollup-linux-ppc64-musl/4.63.5) | MIT |
| [@rollup/rollup-linux-riscv64-gnu 4.63.5](https://registry.npmjs.org/@rollup%2Frollup-linux-riscv64-gnu/4.63.5) | MIT |
| [@rollup/rollup-linux-riscv64-musl 4.63.5](https://registry.npmjs.org/@rollup%2Frollup-linux-riscv64-musl/4.63.5) | MIT |
| [@rollup/rollup-linux-s390x-gnu 4.63.5](https://registry.npmjs.org/@rollup%2Frollup-linux-s390x-gnu/4.63.5) | MIT |
| [@rollup/rollup-linux-x64-gnu 4.63.5](https://registry.npmjs.org/@rollup%2Frollup-linux-x64-gnu/4.63.5) | MIT |
| [@rollup/rollup-linux-x64-musl 4.63.5](https://registry.npmjs.org/@rollup%2Frollup-linux-x64-musl/4.63.5) | MIT |
| [@rollup/rollup-openbsd-x64 4.63.5](https://registry.npmjs.org/@rollup%2Frollup-openbsd-x64/4.63.5) | MIT |
| [@rollup/rollup-openharmony-arm64 4.63.5](https://registry.npmjs.org/@rollup%2Frollup-openharmony-arm64/4.63.5) | MIT |
| [@rollup/rollup-win32-arm64-msvc 4.63.5](https://registry.npmjs.org/@rollup%2Frollup-win32-arm64-msvc/4.63.5) | MIT |
| [@rollup/rollup-win32-ia32-msvc 4.63.5](https://registry.npmjs.org/@rollup%2Frollup-win32-ia32-msvc/4.63.5) | MIT |
| [@rollup/rollup-win32-x64-gnu 4.63.5](https://registry.npmjs.org/@rollup%2Frollup-win32-x64-gnu/4.63.5) | MIT |
| [@rollup/rollup-win32-x64-msvc 4.63.5](https://registry.npmjs.org/@rollup%2Frollup-win32-x64-msvc/4.63.5) | MIT |
| [@types/estree 1.0.9](https://registry.npmjs.org/@types%2Festree/1.0.9) | MIT |
| [esbuild 0.21.5](https://registry.npmjs.org/esbuild/0.21.5) | MIT |
| [fsevents 2.3.3](https://registry.npmjs.org/fsevents/2.3.3) | MIT |
| [nanoid 3.3.19](https://registry.npmjs.org/nanoid/3.3.19) | MIT |
| [picocolors 1.1.1](https://registry.npmjs.org/picocolors/1.1.1) | ISC |
| [postcss 8.5.28](https://registry.npmjs.org/postcss/8.5.28) | MIT |
| [rollup 4.63.5](https://registry.npmjs.org/rollup/4.63.5) | MIT |
| [source-map-js 1.2.1](https://registry.npmjs.org/source-map-js/1.2.1) | BSD-3-Clause |
| [vite 5.4.20](https://registry.npmjs.org/vite/5.4.20) | MIT |
