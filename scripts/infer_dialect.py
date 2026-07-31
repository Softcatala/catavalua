#!/usr/bin/env python3
"""
Infers a clip's Catalan dialect from the town where its source YouTube video
was recorded (most clips come from municipal plenary sessions — the speaker's
home town is a much stronger dialect signal than trying to guess from 3-20s
of audio alone).

Pipeline (mirrors scripts/transcribe.py's step-by-step, idempotent style):

  Step 1 — Fetch video metadata (resumable, run once):
    python scripts/infer_dialect.py --fetch-metadata

    Downloads clips.tsv from the HF dataset repo, finds every distinct source
    video, and fetches its title + channel name via YouTube's public oEmbed
    endpoint (no API key needed). Cached to scripts/reference/.video_cache.json.

  Step 2 — Match videos to towns (fast, re-run freely):
    python scripts/infer_dialect.py --match

    Matches each video's title/channel against scripts/reference/town_dialects.tsv
    and writes scripts/reference/video_town_matches.tsv for manual review —
    NOT every source video is a town-council meeting (this dataset also
    includes Generalitat de Catalunya department seminars, Diputació sessions,
    and personal channels), so matches are tagged with a confidence tier and a
    channel "level" (municipi / provincial-or-generalitat / unknown) rather
    than being applied blindly.

  Step 3 — Apply to the backend (after reviewing the TSV):
    python scripts/infer_dialect.py --apply --min-confidence high

    For every clip whose source video has a match at or above the requested
    confidence, casts a vote (dimension='dialect', targetId=<inferred
    dialecte>, username='derivat-de-poblacio', value=1) via the existing
    POST /votes endpoint — no new backend endpoint needed. This is
    deliberately NOT a direct write to clips.detected_dialect: that column
    holds the audio model's own per-clip guess, and overwriting it would
    lose that value with no history. Casting a vote instead adds our
    geography-derived dialect as a competing candidate that the frontend's
    resolveDimension() will show as the leading value (since the original
    guess has no votes of its own backing it), without touching the clip
    row at all — a real evaluator can still confirm it to "golden" (net>=2)
    or vote it down, and the original model guess is never lost.

Usage:
  python scripts/infer_dialect.py --fetch-metadata
  python scripts/infer_dialect.py --match
  python scripts/infer_dialect.py --apply --min-confidence high [--dry-run]
  python scripts/infer_dialect.py --api-url https://api.your-domain.example ...
"""
import argparse
import csv
import json
import logging
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("infer_dialect")

REF_DIR = Path(__file__).parent / "reference"
CLIPS_TSV_URL = "https://huggingface.co/datasets/softcatala/catalan-youtube-speech/resolve/main/clips.tsv"
CLIPS_TSV_PATH = REF_DIR / ".clips.tsv"
VIDEO_CACHE_PATH = REF_DIR / ".video_cache.json"
GAZETTEER_PATH = REF_DIR / "town_dialects.tsv"
MATCHES_PATH = REF_DIR / "video_town_matches.tsv"

CONFIDENCE_RANK = {"high": 2, "medium": 1, "low": 0}


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def video_id_from_url(yt_url: str) -> str | None:
    m = re.search(r"[?&]v=([\w-]{11})", yt_url) or re.search(r"youtu\.be/([\w-]{11})", yt_url)
    return m.group(1) if m else None


def download_clips_tsv() -> Path:
    if CLIPS_TSV_PATH.exists():
        return CLIPS_TSV_PATH
    log.info("Downloading clips.tsv from HuggingFace (~140MB, one-time)...")
    REF_DIR.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(CLIPS_TSV_URL, CLIPS_TSV_PATH)
    return CLIPS_TSV_PATH


def distinct_source_videos() -> dict[str, dict]:
    """source_id -> {yt_url, video_id}, one entry per distinct source video."""
    path = download_clips_tsv()
    out = {}
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            sid = row["source_id"]
            if sid in out:
                continue
            yt_url = row["yt_url"].split("&t=")[0].split("?t=")[0]
            vid = video_id_from_url(yt_url)
            if vid:
                out[sid] = {"yt_url": yt_url, "video_id": vid}
    return out


# ---------------------------------------------------------------------------
# Step 1 — fetch oEmbed metadata
# ---------------------------------------------------------------------------

def fetch_oembed(yt_url: str, timeout=15) -> dict | None:
    url = "https://www.youtube.com/oembed?" + urllib.parse.urlencode({"url": yt_url, "format": "json"})
    delay = 2
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "catvoice-dialect-inference/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code in (401, 404, 403):
                return None  # video removed/private — no metadata available
            if e.code == 429 and attempt < 3:
                log.warning("rate limited, backing off %ds", delay)
                time.sleep(delay)
                delay *= 2
                continue
            log.warning("oEmbed HTTP error for %s: %s", yt_url, e)
            return None
        except Exception as e:
            if attempt < 3:
                time.sleep(delay)
                delay *= 2
                continue
            log.warning("oEmbed failed for %s: %s", yt_url, e)
            return None
    return None


def cmd_fetch_metadata(args):
    videos = distinct_source_videos()
    log.info("%d distinct source videos", len(videos))

    cache = {}
    if VIDEO_CACHE_PATH.exists():
        cache = json.loads(VIDEO_CACHE_PATH.read_text(encoding="utf-8"))

    todo = [(sid, v) for sid, v in videos.items() if sid not in cache]
    log.info("%d already cached, %d to fetch", len(videos) - len(todo), len(todo))

    for i, (sid, v) in enumerate(todo, 1):
        data = fetch_oembed(v["yt_url"])
        cache[sid] = {
            "yt_url": v["yt_url"],
            "video_id": v["video_id"],
            "title": (data or {}).get("title"),
            "author_name": (data or {}).get("author_name"),
            "found": data is not None,
        }
        if i % 50 == 0 or i == len(todo):
            log.info("fetched %d/%d", i, len(todo))
            VIDEO_CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=0), encoding="utf-8")
        time.sleep(0.15)  # be polite to YouTube's public oEmbed endpoint

    VIDEO_CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=0), encoding="utf-8")
    found = sum(1 for v in cache.values() if v["found"])
    log.info("done: %d/%d videos have metadata", found, len(cache))


# ---------------------------------------------------------------------------
# Step 2 — match videos to towns
# ---------------------------------------------------------------------------

LEADING_ARTICLES = ("el ", "la ", "els ", "les ", "l'")

INSTITUTIONAL_CHANNEL_RE = re.compile(
    r"generalitat|departament|diputaci[oó]|consell comarcal|parlament|govern d'andorra|"
    r"universitat|ministeri|ajuntament\s*$",
    re.IGNORECASE,
)

TRIGGER_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"ajuntament\s+de\s+l['’]?\s*",
        r"ajuntament\s+d['’]",
        r"ajuntament\s+de\s+",
        r"ajuntament\s+del\s+",
        r"ple\s+municipal\s+de\s+l['’]?\s*ajuntament\s+de\s+",
        r"ple\s+municipal\s+d['’]",
        r"ple\s+municipal\s+de\s+",
        r"ple\s+de\s+l['’]?\s*ajuntament\s+de\s+",
        r"constituci[oó]\s+de\s+l['’]?\s*ajuntament\s+de\s+",
        r"ple\s+d['’]",
        r"ple\s+de\s+",
        r"fundaci[oó]\s+ciutat\s+de\s+",
        r"consell\s+comarcal\s+de\s+l['’]?\s*",
        r"consell\s+comarcal\s+d['’]",
        r"consell\s+comarcal\s+de\s+",
        r"consell\s+comarcal\s+del\s+",
    ]
]

# Text after a trigger often continues with junk we should cut off at.
TRAILING_CUT_RE = re.compile(
    r"[\(\[\-–—,\.:]|"
    r"\s+(ple|sessi[oó]|extraordinari|ordinari|de\s+\d|del\s+mes|gener|febrer|març|abril|maig|"
    r"juny|juliol|agost|setembre|octubre|novembre|desembre)\b",
    re.IGNORECASE,
)


# Town names that collide with common Catalan administrative/generic words,
# so the fallback substring scan would otherwise "match" every video whose
# title/channel merely uses the ordinary word (e.g. any "Consell Comarcal de
# X" / "Consell Municipal" phrase falsely matching the town of Consell,
# Mallorca). Trigger-phrase matches (e.g. an actual "Ajuntament de Consell")
# still work fine — this only blocks the untargeted fallback scan.
FALLBACK_STOPWORDS = {"consell"}


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def normalize(s: str) -> str:
    s = strip_accents(s.lower()).strip()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    for art in LEADING_ARTICLES:
        art_n = strip_accents(art)
        if s.startswith(art_n):
            s = s[len(art_n):]
            break
    return s.strip()


def load_gazetteer():
    rows = list(csv.DictReader(GAZETTEER_PATH.open(encoding="utf-8"), delimiter="\t"))
    by_norm = {}
    for r in rows:
        key = normalize(r["town"])
        if key and key not in by_norm:  # first occurrence wins on rare name clashes
            by_norm[key] = r
    return rows, by_norm


def build_fallback_matcher(by_norm: dict):
    """One combined regex (longest names first) instead of ~1800 separate
    re.search calls per video — the per-key version recompiles a fresh
    pattern every time (Python's re cache thrashes past ~512 distinct
    patterns), which made --match take several minutes for 3,119 videos."""
    keys = sorted((k for k in by_norm if len(k) >= 6 and k not in FALLBACK_STOPWORDS), key=len, reverse=True)
    pattern = "|".join(rf"(?<!\w){re.escape(k)}(?!\w)" for k in keys)
    return re.compile(pattern)


def extract_candidate(text: str) -> str | None:
    for pat in TRIGGER_PATTERNS:
        m = pat.search(text)
        if not m:
            continue
        rest = text[m.end():]
        cut = TRAILING_CUT_RE.search(rest)
        candidate = rest[: cut.start()] if cut else rest
        candidate = candidate.strip(" '’\"")
        if candidate:
            return candidate
    return None


def channel_level(author_name: str) -> str:
    if not author_name:
        return "unknown"
    if INSTITUTIONAL_CHANNEL_RE.search(author_name):
        return "provincial-or-generalitat"
    return "municipi"


def match_video(title: str, author_name: str, by_norm: dict, fallback_matcher: re.Pattern) -> tuple[str | None, str, str]:
    """Returns (matched_town_row_key, confidence, source_field)."""
    for field_name, text in (("author_name", author_name), ("title", title)):
        if not text:
            continue
        candidate = extract_candidate(text)
        if not candidate:
            continue
        key = normalize(candidate)
        if key in by_norm:
            return key, "high", field_name
        # try progressively shorter prefixes (candidate may have trailing junk
        # the cut regex didn't catch, e.g. an apostrophe-less contraction)
        words = key.split()
        for n in range(len(words), 0, -1):
            sub = " ".join(words[:n])
            if sub in by_norm:
                return sub, "high", field_name

    # Fallback: scan for the longest gazetteer town name appearing as a whole
    # word/phrase anywhere in title+author. Skip short names — too many false
    # positives (e.g. "Alp", "Coll") without a trigger phrase to anchor them.
    haystack = normalize(f"{author_name or ''} {title or ''}")
    matches = fallback_matcher.finditer(haystack)
    best = max((m.group(0) for m in matches), key=len, default=None)
    if best:
        return best, "medium", "fallback"

    return None, "low", ""


def cmd_match(args):
    if not VIDEO_CACHE_PATH.exists():
        log.error("run --fetch-metadata first")
        sys.exit(1)
    cache = json.loads(VIDEO_CACHE_PATH.read_text(encoding="utf-8"))
    _, by_norm = load_gazetteer()
    fallback_matcher = build_fallback_matcher(by_norm)

    out_rows = []
    tally = {"high": 0, "medium": 0, "low": 0}
    for sid, v in cache.items():
        title = v.get("title") or ""
        author = v.get("author_name") or ""
        if not v.get("found"):
            out_rows.append([sid, v["yt_url"], "", "", "", "", "", "", "not_found", "unknown"])
            tally["low"] += 1
            continue
        key, confidence, field = match_video(title, author, by_norm, fallback_matcher)
        level = channel_level(author)
        if confidence == "high" and field == "title" and level != "municipi":
            # A town name in the *title* only counts as high-confidence when
            # the channel itself is that town's own channel too. Otherwise
            # it's often just a topic mention on an institutional channel
            # (e.g. departamentjusticia covering "l'Ajuntament de Matadepera"
            # as a seminar topic) — not evidence the speaker is from there.
            confidence = "medium"
        if key:
            row = by_norm[key]
            out_rows.append(
                [sid, v["yt_url"], author, title, row["town"], row["comarca"], row["territori"], row["dialecte"], confidence, level]
            )
        else:
            out_rows.append([sid, v["yt_url"], author, title, "", "", "", "", "low", level])
        tally[confidence] += 1

    REF_DIR.mkdir(parents=True, exist_ok=True)
    with MATCHES_PATH.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["source_id", "yt_url", "channel", "title", "town", "comarca", "territori", "dialecte", "confidence", "channel_level"])
        w.writerows(out_rows)

    log.info("wrote %d rows to %s", len(out_rows), MATCHES_PATH)
    log.info("confidence tally: %s", tally)


# ---------------------------------------------------------------------------
# Step 3 — apply to backend
# ---------------------------------------------------------------------------

def http_post_json(url, payload, timeout=15, retries=3):
    delay = 5
    for attempt in range(1, retries + 1):
        try:
            data = json.dumps(payload).encode()
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read())
        except Exception as e:
            if attempt < retries:
                time.sleep(delay)
                delay = min(delay * 2, 60)
                continue
            raise e


def http_get_json(url, timeout=15) -> dict | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    except Exception:
        return None


VOTE_USERNAME = "derivat-de-poblacio"


def clip_exists(api_url: str, clip_id: str) -> bool:
    # Casting a vote for a clip_id that isn't in *this* environment's DB
    # would hit the votes table's FK to clips — check first so we can skip
    # and count those cleanly instead of relying on that to fail loudly.
    return http_get_json(f"{api_url}/clips/{clip_id}") is not None


def _vote_one(api_url: str, clip_id: str, dialecte: str) -> str:
    """Returns 'voted', 'skipped_missing', or 'error:<msg>'."""
    if not clip_exists(api_url, clip_id):
        return "skipped_missing"
    try:
        http_post_json(
            f"{api_url}/votes",
            {
                "clipId": clip_id,
                "dimension": "dialect",
                "targetId": dialecte,
                "username": VOTE_USERNAME,
                "value": 1,
            },
        )
        return "voted"
    except Exception as e:
        return f"error:{e}"


def cmd_apply(args):
    if not MATCHES_PATH.exists():
        log.error("run --match first")
        sys.exit(1)
    matches = list(csv.DictReader(MATCHES_PATH.open(encoding="utf-8"), delimiter="\t"))
    min_rank = CONFIDENCE_RANK[args.min_confidence]
    accepted = {
        m["source_id"]: m["dialecte"]
        for m in matches
        if m["dialecte"] and CONFIDENCE_RANK.get(m["confidence"], -1) >= min_rank
    }
    log.info("%d/%d source videos meet confidence >= %s", len(accepted), len(matches), args.min_confidence)
    log.info("target API: %s%s", args.api_url, " (dry run)" if args.dry_run else "")
    log.info("casting as dialect votes under username=%r (clips.detected_dialect is left untouched)", VOTE_USERNAME)

    path = download_clips_tsv()
    targets = []  # (clip_id, dialecte), deduped — a clip only needs one vote
    seen = set()
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            dialecte = accepted.get(row["source_id"])
            clip_id = row["clip_id"]
            if dialecte and clip_id not in seen:
                seen.add(clip_id)
                targets.append((clip_id, dialecte))
    log.info("%d clips to vote on", len(targets))

    if args.dry_run:
        log.info("would cast on %d clips (dry run, no requests made)", len(targets))
        return

    voted = skipped_missing = errors = 0
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = {pool.submit(_vote_one, args.api_url, cid, d): cid for cid, d in targets}
        for i, fut in enumerate(as_completed(futures), 1):
            result = fut.result()
            if result == "voted":
                voted += 1
            elif result == "skipped_missing":
                skipped_missing += 1
            else:
                errors += 1
                log.warning("clip %s: %s", futures[fut], result)
            if i % 500 == 0:
                log.info("%d/%d done (%d voted, %d skipped, %d errors)", i, len(targets), voted, skipped_missing, errors)

    log.info(
        "cast %d dialect votes (%d skipped: clip not found in %s, %d errors)",
        voted,
        skipped_missing,
        args.api_url,
        errors,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fetch-metadata", action="store_true")
    parser.add_argument("--match", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--min-confidence", choices=["high", "medium", "low"], default="high")
    parser.add_argument("--api-url", default="http://localhost:3000")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--concurrency", type=int, default=20, help="parallel requests for --apply (default 20)")
    args = parser.parse_args()

    if args.fetch_metadata:
        cmd_fetch_metadata(args)
    elif args.match:
        cmd_match(args)
    elif args.apply:
        cmd_apply(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
