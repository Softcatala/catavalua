#!/usr/bin/env python3
"""
Tiny local web UI for reviewing the clips detect_language.py flagged (tier 1
or 2) — i.e. checking for false positives among clips that would actually
get a vote cast under the two-tier rule. Tier-0 (not flagged) clips aren't
shown; there's nothing to review about them.

No database, no build step, stdlib only — same shape as label_ui.py. Reads/
writes detect_sample.tsv directly (review_verdict/review_notes columns),
so progress is never lost and you can stop/resume anytime. Audio stays
under data/language_id/audio/ (gitignored) — already downloaded by
detect_language.py for every clip in the sample.

Usage:
  python scripts/language_id/review_ui.py                 # http://127.0.0.1:8787
  python scripts/language_id/review_ui.py --port 9000

Binds to 127.0.0.1 by default (no auth) — reach it over SSH port forwarding:
  ssh -L 8787:localhost:8787 <host>
then open http://localhost:8787 locally.
"""
import argparse
import csv
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, str(Path(__file__).parent))
from paths import AUDIO_DIR, DETECT_SAMPLE_TSV  # noqa: E402

FIELDNAMES = [
    "clip_id", "duration", "yt_url", "candidate_1", "p_ca_voxlingua", "p_ca_mms", "tier",
    "review_verdict", "review_notes",
]


def load_all_rows() -> list[dict]:
    with DETECT_SAMPLE_TSV.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def save_all_rows(rows: list[dict]) -> None:
    tmp = DETECT_SAMPLE_TSV.with_suffix(".tsv.tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES, delimiter="\t")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(DETECT_SAMPLE_TSV)


def flagged_indices(rows: list[dict]) -> list[int]:
    """Indices of tier>=1 rows, sorted tier 2 (auto-hide, most critical) first."""
    idxs = [i for i, r in enumerate(rows) if int(r["tier"]) >= 1]
    idxs.sort(key=lambda i: (-int(rows[i]["tier"]), rows[i]["clip_id"]))
    return idxs


def first_unreviewed(rows: list[dict], order: list[int]) -> int:
    for i in order:
        if not rows[i]["review_verdict"]:
            return i
    return order[0] if order else 0


PAGE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>LID detection review</title>
<style>
  body { font-family: system-ui, sans-serif; max-width: 640px; margin: 40px auto; padding: 0 16px; color: #222; }
  h1 { font-size: 18px; }
  #progress { color: #666; margin-bottom: 4px; }
  #stats { color: #999; font-size: 13px; margin-bottom: 20px; }
  #tier-badge { display: inline-block; padding: 3px 10px; border-radius: 12px; font-size: 12px; font-weight: 600; margin-bottom: 10px; }
  #tier-badge.tier-2 { background: #fde0e0; color: #a30000; }
  #tier-badge.tier-1 { background: #fff3cd; color: #8a6400; }
  #meta { color: #444; font-size: 14px; margin: 12px 0; line-height: 1.5; }
  #meta a { color: #06c; }
  #candidate { background: #f4f4f4; border-radius: 6px; padding: 10px 12px; font-size: 14px; color: #333; margin: 12px 0; }
  audio { width: 100%; margin: 12px 0; }
  #verdicts { display: flex; gap: 8px; flex-wrap: wrap; margin: 16px 0; }
  #verdicts button { flex: 1 1 auto; padding: 12px 8px; font-size: 15px; border: 2px solid #ccc; border-radius: 6px; background: #fff; cursor: pointer; }
  #verdicts button.selected { border-color: #06c; background: #e8f2ff; font-weight: 600; }
  #verdicts button[data-verdict="false_positive"].selected { border-color: #c00; background: #fde0e0; }
  #notes { width: 100%; box-sizing: border-box; padding: 8px; font-size: 14px; margin: 8px 0 16px; }
  #nav { display: flex; gap: 8px; }
  #nav button { padding: 10px 16px; font-size: 14px; cursor: pointer; }
  #save { background: #06c; color: #fff; border: none; border-radius: 6px; }
  #save:disabled { background: #99c2e8; cursor: not-allowed; }
  #hint { color: #999; font-size: 12px; margin-top: 20px; }
</style>
</head>
<body>
  <h1>Reviewing detected (flagged) clips</h1>
  <div id="progress">loading…</div>
  <div id="stats"></div>
  <div id="tier-badge"></div>
  <div id="meta"></div>
  <div id="candidate"></div>
  <audio id="player" controls autoplay></audio>
  <div id="verdicts">
    <button data-verdict="correct">1 · Correct (really not Catalan)</button>
    <button data-verdict="false_positive">2 · False positive (IS Catalan)</button>
    <button data-verdict="unsure">3 · Unsure</button>
  </div>
  <input id="notes" placeholder="notes (code-switching, music, near-silence…)">
  <div id="nav">
    <button id="prev">◀ Prev</button>
    <button id="save">Save &amp; Next ▶</button>
  </div>
  <div id="hint">Keys 1-3 select a verdict, Enter saves and advances.</div>

<script>
let state = null;
let selectedVerdict = null;

async function loadState(i) {
  const url = i === null ? "/api/state" : `/api/state?i=${i}`;
  const res = await fetch(url);
  state = await res.json();
  selectedVerdict = state.review_verdict || null;
  render();
}

function render() {
  document.getElementById("progress").textContent =
    `Flagged clip ${state.position + 1} / ${state.total} — ${state.done} reviewed`;
  document.getElementById("stats").textContent =
    `${state.false_positives} false positive(s) found so far (${state.tier2_false_positives} at tier 2 / auto-hide)`;
  const badge = document.getElementById("tier-badge");
  badge.textContent = state.tier === 2 ? "TIER 2 — auto-hide (both models agreed)" : "TIER 1 — single vote (needs human)";
  badge.className = state.tier === 2 ? "tier-2" : "tier-1";
  document.getElementById("meta").innerHTML =
    `duration: ${state.duration}s · P(catalan) vox=${state.p_ca_voxlingua} mms=${state.p_ca_mms} · ` +
    `<a href="${state.yt_url}" target="_blank" rel="noopener">open on YouTube</a>`;
  document.getElementById("candidate").textContent = state.candidate_1 || "(no candidate transcription)";
  document.getElementById("notes").value = state.review_notes || "";
  document.querySelectorAll("#verdicts button").forEach(b => {
    b.classList.toggle("selected", b.dataset.verdict === selectedVerdict);
  });
  const player = document.getElementById("player");
  player.src = `/audio/${state.clip_id}.wav`;
  player.play().catch(() => {});
  document.getElementById("prev").disabled = state.position === 0;
}

async function save(advance) {
  const notes = document.getElementById("notes").value;
  const res = await fetch("/api/review", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ index: state.index, clip_id: state.clip_id, verdict: selectedVerdict || "", notes }),
  });
  const result = await res.json();
  if (result.error) { alert(result.error); return; }
  if (advance) {
    await loadState(result.next_position);
  } else {
    await loadState(state.position);
  }
}

document.querySelectorAll("#verdicts button").forEach(b => {
  b.addEventListener("click", () => {
    selectedVerdict = b.dataset.verdict;
    render();
  });
});
document.getElementById("save").addEventListener("click", () => save(true));
document.getElementById("prev").addEventListener("click", () => loadState(Math.max(0, state.position - 1)));

document.addEventListener("keydown", (e) => {
  if (document.activeElement.id === "notes") {
    if (e.key === "Enter") { e.preventDefault(); save(true); }
    return;
  }
  if (["1", "2", "3"].includes(e.key)) {
    selectedVerdict = ["correct", "false_positive", "unsure"][Number(e.key) - 1];
    render();
  } else if (e.key === "Enter") {
    save(true);
  }
});

loadState(null);
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def _json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            body = PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if parsed.path == "/api/state":
            rows = load_all_rows()
            order = flagged_indices(rows)
            qs = parse_qs(parsed.query)
            pos = int(qs["i"][0]) if "i" in qs else order.index(first_unreviewed(rows, order))
            pos = max(0, min(pos, len(order) - 1))
            idx = order[pos]
            row = rows[idx]
            done = sum(1 for i in order if rows[i]["review_verdict"])
            false_positives = sum(1 for i in order if rows[i]["review_verdict"] == "false_positive")
            tier2_fp = sum(1 for i in order if rows[i]["review_verdict"] == "false_positive" and int(rows[i]["tier"]) == 2)
            self._json({
                "index": idx,
                "position": pos,
                "total": len(order),
                "done": done,
                "false_positives": false_positives,
                "tier2_false_positives": tier2_fp,
                "clip_id": row["clip_id"],
                "duration": row["duration"],
                "yt_url": row["yt_url"],
                "candidate_1": row["candidate_1"],
                "p_ca_voxlingua": row["p_ca_voxlingua"],
                "p_ca_mms": row["p_ca_mms"],
                "tier": int(row["tier"]),
                "review_verdict": row["review_verdict"],
                "review_notes": row["review_notes"],
            })
            return

        if parsed.path.startswith("/audio/"):
            clip_id = Path(parsed.path[len("/audio/"):]).name  # strip any path traversal
            fp = AUDIO_DIR / clip_id
            if not fp.is_file() or fp.resolve().parent != AUDIO_DIR.resolve():
                self.send_error(404)
                return
            data = fp.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        self.send_error(404)

    def do_POST(self):
        if self.path != "/api/review":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length))
        rows = load_all_rows()
        order = flagged_indices(rows)
        idx = payload.get("index")
        clip_id = payload.get("clip_id")
        if idx is None or not (0 <= idx < len(rows)) or rows[idx]["clip_id"] != clip_id:
            self._json({"error": "index/clip_id mismatch — reload the page"}, status=409)
            return
        rows[idx]["review_verdict"] = payload.get("verdict", "")
        rows[idx]["review_notes"] = payload.get("notes", "")
        save_all_rows(rows)
        pos = order.index(idx)
        next_position = pos + 1 if pos + 1 < len(order) else pos
        self._json({"saved": True, "next_position": next_position})

    def log_message(self, fmt, *args):
        pass  # quiet — local single-user tool


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()

    if not DETECT_SAMPLE_TSV.exists():
        raise SystemExit(f"{DETECT_SAMPLE_TSV} not found — run scripts/language_id/detect_language.py first")

    rows = load_all_rows()
    n_flagged = len(flagged_indices(rows))
    if n_flagged == 0:
        raise SystemExit(f"no tier>=1 (flagged) clips in {DETECT_SAMPLE_TSV} — nothing to review")

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Review UI at http://{args.host}:{args.port}  ({n_flagged} flagged clips to review, Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
