# Second-pass punctuated transcription (issue #8)

[Softcatala/garbellaveus#8](https://github.com/Softcatala/garbellaveus/issues/8):
beta feedback found practically all clips have unpunctuated transcriptions.
This directory adds a second transcription candidate — from
**whisper-large-v3-turbo**, run directly and batched via CTranslate2 — over
every clip the language-ID pass ([`scripts/language_id/`](../language_id/))
did NOT flag as non-Catalan, so evaluators get a punctuated option to
compare against and vote on.

This is a plan-and-tooling commit: the scripts below are ready to run, but
no pod has been provisioned and nothing has been transcribed yet. Run
`pilot_transcribe.py` locally first (see "Workflow" below) before spending
anything on a rented GPU.

## Scope

Only **tier 0** clips from `scripts/language_id/`'s full-dataset LID run —
neither of its two models flagged the clip as non-Catalan. Tier 1 (one
model flagged it — still visible, single vote) and tier 2 (both flagged it
— auto-hidden) are excluded, same as that pipeline's own vote-casting run.

```
data/language_id/full_detect.tsv: 180,443 tier-0 clips, 729.0 hours of audio
```

(The ~482 clips in `ground_truth.tsv`/`detect_sample.tsv` — hand-labeled or
held out during the LID investigation, never scored into `full_detect.tsv`
— are excluded here too, consistent with how the LID vote-casting run
itself scoped its work. ~0.2% of the dataset.)

## Tool decisions

### Custom batched script, not `Softcatala/whisper-ctranslate2`

`whisper-ctranslate2` (also a Softcatala project, same org as the dataset)
was evaluated first. Its CLI conveniently accepts many audio files in one
invocation and keeps the model loaded across them — but reading its actual
transcribe loop shows it calls `transcribe.inference()` **once per file,
sequentially**:

```python
for audio_path in audio:
    result = transcribe.inference(audio_path, task, language, ...)
```

Its `--batched` flag batches the *VAD segments within one file* for
parallel decoding — not *across* files. Since every clip here is already a
single pre-segmented utterance (3-20s, one VAD segment at most), that
flag has ~nothing to batch per clip against this workload. Run as-is
against 180k separate files, it would behave like unbatched single-stream
inference. It's also VAD-on-by-default for its batched path, and per the
task for this pass, VAD isn't wanted at all (see below).

Instead, `whisper_engine.py` batches many *different* clips into one GPU
forward pass directly — the same approach
[`scripts/language_id/pod/batch_models.py`](../language_id/pod/batch_models.py)
already uses for the two LID models. It's built on
[`faster-whisper`](https://github.com/SYSTRAN/faster-whisper)'s low-level
pieces (`WhisperModel`'s already-correct model/tokenizer/feature-extractor
loading, then `ctranslate2.models.Whisper.generate()` called directly on a
stacked batch) rather than its `.transcribe()` / `BatchedInferencePipeline`
API, which has the same one-file-at-a-time limitation as
whisper-ctranslate2 for this shape of workload.

### No VAD

Every clip is already a single pre-cut utterance from the dataset's own
segmentation — there's no silence to trim and no multi-speaker turns to
detect. VAD here is pure overhead, and a source of clipped-word risk at the
segment boundary, for zero benefit. `whisper_engine.py` never touches it:
every clip is padded/truncated straight to Whisper's fixed 30-second
encoder window and transcribed whole.

### Model: `large-v3-turbo` (faster-whisper's own repo mapping)

`whisper_engine.py` passes the shorthand `"large-v3-turbo"` to
`faster_whisper.WhisperModel`, which resolves it via the library's own
built-in `_MODELS` mapping rather than a repo id hardcoded in this
pipeline — so it always tracks whichever CTranslate2 conversion
faster-whisper itself considers canonical (that mapping already changed
once, when the repo it names got renamed/transferred on HF; using the
shorthand means the library absorbs moves like that automatically). It's a
lossless CT2 re-serialization of `openai/whisper-large-v3-turbo`'s own
weights — no fine-tuning divergence between different CT2 conversions of
the same checkpoint — so it inherits Whisper's native Catalan support
as-is (see CrisperWhisper below for a model where that's *not* true).

For context: Softcatalà's own production transcription service
([`Softcatala/transcribe-service`](https://github.com/Softcatala/transcribe-service))
uses `medium` (`Systran/faster-whisper-medium`, via their own
`whisper-ctranslate2` CLI, CPU, `int8`) — the largest size baked into their
Docker image, sized for a live multi-tenant web service on modest CPU
hardware. That's a different cost/latency tradeoff than a one-off batch job
on a rented GPU, which is why `large-v3-turbo` is worth it here. Notably,
Softcatalà doesn't rely on Whisper for punctuation at all: their
[`punctuation-service`](https://github.com/Softcatala/punctuation-service)
is a separate, dedicated mT5 restoration model applied as post-processing
to already-transcribed text. That approach is cheaper but only fixes
punctuation — it can't recover words the underlying ASR got wrong, which a
real re-transcription pass does (the pilot run below shows a concrete
example: `"sis marrades mildred"` → `"6/2013"`, not just added commas).
This pipeline does a real second transcription pass specifically to get
both — punctuation *and* an actual accuracy improvement over the original
candidates.

### CrisperWhisper — evaluated, not used as the primary model

[CrisperWhisper 2.0](https://huggingface.co/nyralabs/CrisperWhisper2.0_turbo)
specializes in exactly the kind of thing this dataset's original ASR
candidates are missing in a different way — not punctuation, but verbatim
disfluencies (fillers, false starts, repetitions). It was considered and
rejected as the primary model for the full run:

- **Catalan is untested.** Its disfluency fine-tuning is benchmarked across
  ten languages (English, German + 8 more); Catalan isn't one of them, and
  its HF model card tags only `en`/`de`. The README's own claim is
  "works across most languages Whisper supports" — a hedge, not a
  guarantee. Quality on Catalan is genuinely unknown, not disqualified
  outright, which is why it's kept as an optional side experiment rather
  than dropped entirely.
- **License friction.** Its weights are under the Nyra Health
  Non-Commercial Research License, not MIT. This dataset is CC-BY, which
  permits downstream commercial reuse — a non-commercially-licensed
  transcription sitting inside it is a mismatch worth avoiding rather than
  untangling later.
- **Not this issue's goal.** Issue #8 is specifically about punctuation.
  Vanilla Whisper already produces it (see below); CrisperWhisper's real
  differentiator (verbatim fillers) is a separate concern this pass isn't
  targeting.

[`pilot_compare_crisperwhisper.py`](pilot_compare_crisperwhisper.py) runs
it on the same small sample as the main pilot, purely to see real Catalan
output before ruling it out further — not part of the full-dataset run.

### Punctuation vs. filler words

Whisper (all sizes, including large-v3-turbo) is trained on largely
punctuated caption/subtitle data, so punctuation output is expected and is
exactly what this pass is for. Filler words are a different story: Whisper
is well known to suppress "um"/"uh" by training bias (it was trained on
cleaned transcripts) even though other disfluencies partially leak through
on longer audio — so **don't expect this pass to add fillers back**; that
was never its goal here (contrast with `scripts/transcribe.py`'s Gemini
prompt, which explicitly asks for verbatim fillers and explicitly asks for
*no* punctuation — the two passes are deliberately complementary, not
duplicates).

## Workflow

```bash
# 1. Build the clip list (tier-0 only) — local, no GPU, seconds to run.
python scripts/whisper_transcribe/select_clips.py

# 2. First short pass — local CPU is fine, no pod yet. Confirms punctuation
#    shows up before spending anything on a rented GPU.
python scripts/whisper_transcribe/pilot_transcribe.py --n 15

# 2b. Optional: same sample through CrisperWhisper, for comparison only.
pip install "crisperwhisper[ct2]"
python scripts/whisper_transcribe/pilot_compare_crisperwhisper.py --n 15

# 3. Only once the pilot looks right — provision a pod (48GB VRAM is
#    comfortably enough; the model itself is <2GB) and mirror
#    scripts/language_id/pod/README.md's sequence:
rsync -av scripts/whisper_transcribe/ gpu-machine:~/catvoice/scripts/whisper_transcribe/
#    (also needs data/clips.tsv, data/tar_index.json, data/language_id/full_detect.tsv,
#     and scripts/whisper_transcribe/paths.py's REPO_ROOT-relative layout preserved)

# on the pod:
bash scripts/whisper_transcribe/pod/setup_env.sh
source ~/venv/bin/activate
bash scripts/whisper_transcribe/pod/download_tars.sh ~/tars 6
nohup python scripts/whisper_transcribe/pod/run_full_transcription.py \
  --tar-dir ~/tars \
  --out /path/to/persistent/storage/whisper_transcriptions.tsv \
  --device cuda:0 --batch-size 16 \
  --cache-dir ~/.model_cache \
  < /dev/null > ~/full_run.log 2>&1 &
disown

# 4. Copy whisper_transcriptions.tsv back to data/whisper_transcribe/, then
#    review a sample of it before posting anything.

# 5. Post to a running backend (dry run by default, --apply to actually write):
python scripts/whisper_transcribe/post_transcriptions.py --api-url http://localhost:3000
python scripts/whisper_transcribe/post_transcriptions.py --api-url http://localhost:3000 --apply

# 6. Terminate the pod once the output is safely copied back.
```

Posted transcriptions land with `origin="whisper-large-v3-turbo"` — a new
candidate alongside the existing `candidate_1`/`candidate_2`/Gemini rows,
starting at 0 votes like any other. **How punctuated candidates get
prioritized in the voting UI is a separate, not-yet-decided follow-up**
(issue #8's own open item) — out of scope here.

## Files

| file | purpose |
|---|---|
| `README.md` | this document |
| `paths.py` | shared path/constant module |
| `select_clips.py` | builds `data/whisper_transcribe/clips_to_transcribe.tsv` from `full_detect.tsv` tier-0 rows + `tar_index.json` |
| `local_audio.py` | local tar-seek audio reader (duplicated from `language_id/pod/`, see its docstring) |
| `whisper_engine.py` | the actual batched CTranslate2 inference code — see its docstring for the full "why not whisper-ctranslate2" reasoning |
| `pilot_transcribe.py` | first short pass — small sample, HTTP range fetch, no pod, prints output + a punctuation check |
| `pilot_compare_crisperwhisper.py` | optional side experiment against CrisperWhisper 2.0 — not part of the main pipeline |
| `post_transcriptions.py` | posts the pod run's output to a backend (`POST /transcriptions`), dry-run by default |
| `pod/setup_env.sh` | one-time pod environment setup (`faster-whisper` + `soundfile` only — no VAD/diarization deps) |
| `pod/download_tars.sh` | resumable parallel download of all 51 HF tar files (duplicated from `language_id/pod/`) |
| `pod/run_full_transcription.py` | main driver — idempotent, interruptible, incremental writes, mirrors `language_id/pod/run_full_detection.py` |
| `../../data/whisper_transcribe/` | **no** (gitignored) — clip-selection TSV, model cache, pod output; all regenerable |
