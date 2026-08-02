"""
Batched, device-parametrized versions of the two LID models for the pod
run. Mirrors ../lid_models.py's per-clip logic (same label normalization,
same P(catalan) extraction) but:
  - takes raw audio arrays (already decoded in memory) instead of file
    paths, since run_full_detection.py reads straight out of local tar
    files with no per-clip audio file ever touching disk
  - batches multiple clips per forward pass with proper padding/masking
  - runs on CUDA when available (falls back to CPU — useful for testing
    this code path locally before it ever touches a pod)

Validated against ../lid_models.py's per-clip (unbatched) predictions on
ground_truth.tsv before being trusted for the full run — see REPORT.md.
"""
import numpy as np
import torch


def load_mms(device: str, cache_dir: str):
    from transformers import AutoFeatureExtractor, Wav2Vec2ForSequenceClassification

    model_id = "facebook/mms-lid-126"
    processor = AutoFeatureExtractor.from_pretrained(model_id, cache_dir=cache_dir)
    model = Wav2Vec2ForSequenceClassification.from_pretrained(model_id, cache_dir=cache_dir)
    model.eval()
    model.to(device)
    label2id = {v: k for k, v in model.config.id2label.items()}
    ca_idx = label2id["cat"]
    return processor, model, ca_idx


def run_mms_batch(processor, model, ca_idx: int, device: str, audio_arrays: list[np.ndarray]) -> list[float]:
    inputs = processor(audio_arrays, sampling_rate=16000, return_tensors="pt", padding=True)
    inputs = {k: v.to(device) for k, v in inputs.items()}
    with torch.no_grad():
        logits = model(**inputs).logits
    probs = torch.softmax(logits, dim=-1)
    return probs[:, ca_idx].cpu().tolist()


def load_voxlingua(device: str, savedir: str):
    from speechbrain.inference.classifiers import EncoderClassifier

    clf = EncoderClassifier.from_hparams(
        source="speechbrain/lang-id-voxlingua107-ecapa",
        savedir=savedir,
        run_opts={"device": device},
    )
    ind2lab = {i: lab.split(":")[0].strip() for i, lab in clf.hparams.label_encoder.ind2lab.items()}
    lab2ind = {v: k for k, v in ind2lab.items()}
    ca_idx = lab2ind["ca"]
    return clf, ca_idx


def run_voxlingua_batch(clf, ca_idx: int, device: str, audio_arrays: list[np.ndarray]) -> list[float]:
    lengths = [len(a) for a in audio_arrays]
    max_len = max(lengths)
    padded = torch.zeros(len(audio_arrays), max_len)
    for i, a in enumerate(audio_arrays):
        padded[i, : len(a)] = torch.from_numpy(a).float()
    wav_lens = torch.tensor([l / max_len for l in lengths])
    padded, wav_lens = padded.to(device), wav_lens.to(device)
    with torch.no_grad():
        out_prob, _score, _index, _text_lab = clf.classify_batch(padded, wav_lens)
    probs = out_prob.exp()
    return probs[:, ca_idx].cpu().tolist()
