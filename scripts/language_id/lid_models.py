"""
Runs the two candidate language-ID models (chosen for architecture +
training-data diversity — see REPORT.md) over a batch of local audio files.

Both return, per clip_id: p_ca (probability mass on Catalan), top_lang (best
guess, normalized to ISO 639-1 so the two models' Catalan label agrees — the
Catalan class is 'ca' in VoxLingua107's ISO 639-1 labels but 'cat' in
mms-lid-126's ISO 639-3 labels), and top_prob (confidence in that guess).
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from paths import AUDIO_DIR, MODEL_CACHE_DIR  # noqa: E402

log = logging.getLogger("lid_models")


def run_voxlingua(clip_ids: list[str]) -> dict[str, dict]:
    from speechbrain.inference.classifiers import EncoderClassifier

    log.info("loading speechbrain/lang-id-voxlingua107-ecapa …")
    clf = EncoderClassifier.from_hparams(
        source="speechbrain/lang-id-voxlingua107-ecapa",
        savedir=str(MODEL_CACHE_DIR / "voxlingua"),
    )
    # Labels are "xx: Full Language Name" (e.g. "ca: Catalan") — normalize to the ISO code.
    ind2lab = {i: lab.split(":")[0].strip() for i, lab in clf.hparams.label_encoder.ind2lab.items()}
    lab2ind = {v: k for k, v in ind2lab.items()}
    ca_idx = lab2ind["ca"]

    out = {}
    for i, clip_id in enumerate(clip_ids, 1):
        signal = clf.load_audio(str(AUDIO_DIR / f"{clip_id}.wav"))
        out_prob, _score, index, _text_lab = clf.classify_batch(signal.unsqueeze(0))
        probs = out_prob.exp()[0]
        top_idx = int(index[0])
        out[clip_id] = {
            "p_ca": float(probs[ca_idx]),
            "top_lang": ind2lab[top_idx],
            "top_prob": float(probs[top_idx]),
        }
        if i % 20 == 0 or i == len(clip_ids):
            log.info("voxlingua-ecapa: %d/%d", i, len(clip_ids))
    return out


def run_mms(clip_ids: list[str]) -> dict[str, dict]:
    import torch
    import soundfile as sf
    from transformers import AutoFeatureExtractor, Wav2Vec2ForSequenceClassification

    log.info("loading facebook/mms-lid-126 (large — first run downloads ~1B params) …")
    model_id = "facebook/mms-lid-126"
    processor = AutoFeatureExtractor.from_pretrained(model_id, cache_dir=str(MODEL_CACHE_DIR / "mms"))
    model = Wav2Vec2ForSequenceClassification.from_pretrained(model_id, cache_dir=str(MODEL_CACHE_DIR / "mms"))
    model.eval()
    id2label = model.config.id2label
    label2id = {v: k for k, v in id2label.items()}
    ca_idx = label2id["cat"]

    out = {}
    for i, clip_id in enumerate(clip_ids, 1):
        audio, sr = sf.read(str(AUDIO_DIR / f"{clip_id}.wav"))
        assert sr == 16000, f"{clip_id}: unexpected sample rate {sr}"
        inputs = processor(audio, sampling_rate=sr, return_tensors="pt")
        with torch.no_grad():
            logits = model(**inputs).logits[0]
        probs = torch.softmax(logits, dim=-1)
        top_idx = int(torch.argmax(probs))
        # mms-lid-126 uses ISO 639-3 ('cat'); normalize just the Catalan label
        # to 'ca' so both models' top_lang fields agree on what "is Catalan" means.
        top_lang = id2label[top_idx]
        if top_lang == "cat":
            top_lang = "ca"
        out[clip_id] = {
            "p_ca": float(probs[ca_idx]),
            "top_lang": top_lang,
            "top_prob": float(probs[top_idx]),
        }
        if i % 20 == 0 or i == len(clip_ids):
            log.info("mms-lid-126: %d/%d", i, len(clip_ids))
    return out
