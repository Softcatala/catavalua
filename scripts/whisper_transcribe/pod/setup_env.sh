#!/usr/bin/env bash
# One-time environment setup on the rented GPU machine. Assumes a
# PyTorch + CUDA base image isn't required here — ctranslate2's PyPI wheel
# bundles its own CUDA runtime, same as scripts/language_id's pod setup
# assumed for torch. Installs only what's needed for batched CTranslate2
# whisper-large-v3-turbo inference (see ../whisper_engine.py) — no VAD
# libraries, no diarization stack, unlike whisper-ctranslate2's full
# dependency set, since neither is used here.
set -euo pipefail

python3 -m venv /root/venv
source /root/venv/bin/activate
pip install --upgrade pip -q
pip install -q faster-whisper soundfile
python3 -c "
import ctranslate2
print('ctranslate2', ctranslate2.__version__)
print('cuda device count:', ctranslate2.get_cuda_device_count())
"
echo "Environment ready. Activate with: source /root/venv/bin/activate"
