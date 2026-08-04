"""
Batched, device-parametrized whisper-large-v3-turbo inference (CTranslate2),
built directly on faster-whisper's low-level building blocks instead of its
WhisperModel.transcribe() / BatchedInferencePipeline API — deliberately, for
two reasons (see ../README.md for the full writeup):

  1. No VAD. Every clip in this dataset is already a single pre-segmented
     utterance (3-20s) — there's no silence to trim and no multi-speaker
     turn-taking to detect, so voice-activity detection is pure overhead
     (and a source of clipped-word risk) that both faster-whisper's
     BatchedInferencePipeline and Softcatala/whisper-ctranslate2 turn on
     by default for their batching paths.

  2. True cross-clip batching. faster-whisper's "--batched" mode batches
     the VAD segments *within one audio file* for parallel decoding — it
     still processes files one at a time (confirmed by reading
     whisper-ctranslate2's source: it loops `for audio_path in audio:
     transcribe.inference(audio_path, ...)`, one model call per file).
     That gives no throughput benefit here, since each of our clips has
     ~one segment total. What actually pays off at 180k-clip scale is
     batching many *different* clips into one forward pass — the same
     approach scripts/language_id/pod/batch_models.py already uses for the
     two LID models. This module does that directly against
     ctranslate2.models.Whisper.generate(), which is exactly what
     BatchedInferencePipeline.generate_segment_batched() calls internally
     (verified against faster-whisper's source) — just fed independent
     clips instead of one file's VAD segments.

Model loading still goes through faster_whisper.WhisperModel's constructor
(for its already-correct model/tokenizer/feature-extractor setup — n_mels
differs between whisper-large-v2 (80) and v3/turbo (128), and WhisperModel
reads the right value from the model's preprocessor_config.json instead of
guessing); only .transcribe() itself is bypassed.
"""
import numpy as np

N_FRAMES_30S = 3000  # Whisper's fixed encoder input window, in mel frames (30s at a 10ms hop)


def default_compute_type(device: str) -> str:
    return "float16" if device.startswith("cuda") else "int8"


def load_model(model_id: str, device: str, compute_type: str, cache_dir: str, language: str):
    from faster_whisper import WhisperModel
    from faster_whisper.tokenizer import Tokenizer

    # faster-whisper's device param takes "cpu"/"cuda"/"auto" plus a separate
    # device_index — not PyTorch-style "cuda:0" — so split that out here if
    # given (callers/CLIs in this pipeline default to "cuda:0" for
    # familiarity with the language_id scripts' torch-based convention).
    device_index = 0
    if ":" in device:
        device, index_str = device.split(":", 1)
        device_index = int(index_str)

    wm = WhisperModel(model_id, device=device, device_index=device_index, compute_type=compute_type, download_root=cache_dir)
    tokenizer = Tokenizer(wm.hf_tokenizer, wm.model.is_multilingual, task="transcribe", language=language)
    return wm, tokenizer


def _pad_or_trim_frames(features: np.ndarray) -> np.ndarray:
    """Pads/trims a (n_mels, n_frames) feature array to exactly 3000 frames
    along the frame axis. Deliberately pads the *feature* array, not the
    raw waveform — faster-whisper's own feature extractor doesn't
    guarantee a fixed frame count for a given chunk_length (confirmed
    empirically: a 30s-padded waveform still came out at 3001 frames, one
    off from the nominal 3000 — a centered-STFT rounding artifact), so
    normalizing after extraction is the only way to get a stackable,
    uniform batch shape."""
    n_frames = features.shape[1]
    if n_frames >= N_FRAMES_30S:
        return features[:, :N_FRAMES_30S]
    pad_width = N_FRAMES_30S - n_frames
    return np.pad(features, ((0, 0), (0, pad_width)), constant_values=features.min())


def transcribe_batch(wm, tokenizer, audio_arrays: list[np.ndarray], beam_size: int = 5) -> list[str]:
    """Transcribes N independent clips in one forward pass.

    No VAD, no chunking — every clip is well under Whisper's 30s encoder
    window, so each one's mel features are padded/trimmed to exactly 3000
    frames and stacked into a single batch. Punctuation and casing are left
    exactly as the model produces them — this pipeline exists specifically
    to get a *punctuated* candidate (issue #8); contrast with
    scripts/transcribe.py's Gemini prompt, which explicitly asks for
    verbatim text with punctuation withheld.
    """
    import ctranslate2

    if not audio_arrays:
        return []

    feats = [_pad_or_trim_frames(wm.feature_extractor(a, chunk_length=30)) for a in audio_arrays]
    features = np.stack(feats).astype(np.float32)

    encoder_output = wm.model.encode(ctranslate2.StorageView.from_array(features))
    prompt = list(tokenizer.sot_sequence) + [tokenizer.no_timestamps]
    prompts = [prompt] * len(audio_arrays)

    results = wm.model.generate(
        encoder_output,
        prompts,
        beam_size=beam_size,
        suppress_blank=True,
        suppress_tokens=[-1],
    )
    return [tokenizer.decode(r.sequences_ids[0]).strip() for r in results]
