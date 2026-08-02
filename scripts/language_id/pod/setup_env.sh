#!/usr/bin/env bash
# One-time environment setup on the pod. Assumes the "Runpod Pytorch 2.8.0"
# base image (torch + CUDA already present) — installs only what's missing.
set -euo pipefail

python3 -m venv /workspace/venv
source /workspace/venv/bin/activate
pip install --upgrade pip -q
pip install -q transformers speechbrain soundfile
python3 -c "import torch; print('torch', torch.__version__, 'cuda available:', torch.cuda.is_available())"
echo "Environment ready. Activate with: source /workspace/venv/bin/activate"
