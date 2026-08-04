"""Shared path/constant module for the second-pass punctuated-transcription
pipeline (issue #8: https://github.com/Softcatala/garbellaveus/issues/8).

scripts/whisper_transcribe/  — tracked in git: code + README only.
data/whisper_transcribe/     — gitignored (data/ is fully ignored repo-wide):
                                clip-selection TSVs and pod run output, both
                                regenerable (selection from full_detect.tsv +
                                tar_index.json, transcriptions from re-running
                                the pod against the same clip list).
"""
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
WT_DIR = Path(__file__).parent
DATA_DIR = REPO_ROOT / "data" / "whisper_transcribe"

CLIPS_TSV_FILE = REPO_ROOT / "data" / "clips.tsv"
TAR_INDEX_FILE = REPO_ROOT / "data" / "tar_index.json"

# Output of scripts/language_id's full-dataset LID run (see
# scripts/language_id/REPORT.md) — tier 0 = neither model flagged the clip
# non-Catalan, tier 1 = one model did (single vote, still visible), tier 2 =
# both did (auto-hidden). This pipeline only transcribes tier 0.
FULL_DETECT_TSV = REPO_ROOT / "data" / "language_id" / "full_detect.tsv"

CLIPS_TO_TRANSCRIBE_TSV = DATA_DIR / "clips_to_transcribe.tsv"
OUTPUT_TSV = DATA_DIR / "whisper_transcriptions.tsv"
MODEL_CACHE_DIR = DATA_DIR / ".model_cache"
AUDIO_DIR = DATA_DIR / "audio"  # pilot script only — small, per-clip temp WAVs

# faster-whisper's own shorthand for the CTranslate2 conversion of
# openai/whisper-large-v3-turbo — resolves via its built-in _MODELS mapping
# (faster_whisper/utils.py) rather than a hardcoded community repo id, so
# this tracks whichever repo the library itself considers canonical (that
# mapping already changed once — the repo it names was renamed/transferred
# on HF after this was first picked — using the shorthand means faster-whisper
# absorbs moves like that instead of this pipeline silently pointing at a
# stale/renamed repo). Unlike the fine-tuned alternatives considered (see
# README.md), it's a lossless CT2 re-serialization of the base model's own
# weights, so it inherits Whisper's native Catalan support as-is — there's
# no fine-tuning divergence to worry about between different CT2 conversions
# of the same base checkpoint.
WHISPER_MODEL_ID = "large-v3-turbo"
LANGUAGE = "ca"

# Origin string this pipeline posts transcriptions under (apps/backend
# transcriptions.origin column — see apps/backend/src/domain/transcription.entity.ts).
ORIGIN = "whisper-large-v3-turbo"
