"""Shared path constants for the language-ID research scripts (see REPORT.md).

scripts/language_id/  — tracked in git: the report, ground truth, and code.
data/language_id/     — gitignored (data/ is fully ignored repo-wide): audio
                         and downloaded model weights, both regenerable
                         (audio from the clip_id via the HF tar index, models
                         from their HuggingFace repos).
"""
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
LID_DIR = Path(__file__).parent
DATA_DIR = REPO_ROOT / "data" / "language_id"

CLIPS_TSV_FILE = REPO_ROOT / "data" / "clips.tsv"
TAR_INDEX_FILE = REPO_ROOT / "data" / "tar_index.json"

AUDIO_DIR = DATA_DIR / "audio"
MODEL_CACHE_DIR = DATA_DIR / ".model_cache"

GROUND_TRUTH_TSV = LID_DIR / "ground_truth.tsv"
PREDICTIONS_CACHE = LID_DIR / "model_predictions.json"
DETECT_SAMPLE_TSV = LID_DIR / "detect_sample.tsv"

# The two-tier vote rule settled on in REPORT.md, validated against
# ground_truth.tsv: both models below STRICT -> 2 votes (auto-hides the
# clip immediately); either model below LOOSE -> 1 vote (needs a second,
# human, vote to hide it).
STRICT_THRESHOLD = 0.05
LOOSE_THRESHOLD = 0.1
