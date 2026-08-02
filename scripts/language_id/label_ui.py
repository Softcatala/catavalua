#!/usr/bin/env python3
"""
Tiny local web UI for hand-labeling the LID ground-truth sample produced by
build_ground_truth.py.

No database, no build step, stdlib only. Reads/writes ground_truth.tsv
directly — every save rewrites the TSV in place, so progress is never lost
and you can stop/resume anytime. Audio stays under data/language_id/audio/
(gitignored).

Usage:
  python scripts/language_id/label_ui.py                 # http://127.0.0.1:8787
  python scripts/language_id/label_ui.py --port 9000

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
from paths import AUDIO_DIR, GROUND_TRUTH_TSV as SAMPLE_TSV  # noqa: E402

FIELDNAMES = ["clip_id", "duration", "yt_url", "candidate_1", "ground_truth_lang", "notes", "source"]


def load_rows() -> list[dict]:
    with SAMPLE_TSV.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def save_rows(rows: list[dict]) -> None:
    tmp = SAMPLE_TSV.with_suffix(".tsv.tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES, delimiter="\t")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(SAMPLE_TSV)


def first_unlabeled(rows: list[dict]) -> int:
    for i, r in enumerate(rows):
        if not r["ground_truth_lang"]:
            return i
    return 0


PAGE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>LID labeling</title>
<style>
  body { font-family: system-ui, sans-serif; max-width: 640px; margin: 40px auto; padding: 0 16px; color: #222; }
  h1 { font-size: 18px; }
  #progress { color: #666; margin-bottom: 20px; }
  #meta { color: #444; font-size: 14px; margin: 12px 0; line-height: 1.5; }
  #meta a { color: #06c; }
  #candidate { background: #f4f4f4; border-radius: 6px; padding: 10px 12px; font-size: 14px; color: #333; margin: 12px 0; }
  audio { width: 100%; margin: 12px 0; }
  #langs { display: flex; gap: 8px; flex-wrap: wrap; margin: 16px 0; }
  #langs button { flex: 1 1 auto; padding: 12px 8px; font-size: 15px; border: 2px solid #ccc; border-radius: 6px; background: #fff; cursor: pointer; }
  #langs button.selected { border-color: #06c; background: #e8f2ff; font-weight: 600; }
  #notes { width: 100%; box-sizing: border-box; padding: 8px; font-size: 14px; margin: 8px 0 16px; }
  #nav { display: flex; gap: 8px; }
  #nav button { padding: 10px 16px; font-size: 14px; cursor: pointer; }
  #save { background: #06c; color: #fff; border: none; border-radius: 6px; }
  #save:disabled { background: #99c2e8; cursor: not-allowed; }
  #hint { color: #999; font-size: 12px; margin-top: 20px; }
</style>
</head>
<body>
  <h1>Language ID ground-truth labeling</h1>
  <div id="progress">loading…</div>
  <div id="meta"></div>
  <div id="candidate"></div>
  <audio id="player" controls autoplay></audio>
  <div id="langs">
    <button data-lang="ca">1 · Catalan</button>
    <button data-lang="es">2 · Spanish</button>
    <button data-lang="en">3 · English</button>
    <button data-lang="other">4 · Other</button>
    <button data-lang="unsure">5 · Unsure</button>
  </div>
  <input id="notes" placeholder="notes (code-switching, music, near-silence…)">
  <div id="nav">
    <button id="prev">◀ Prev</button>
    <button id="save">Save &amp; Next ▶</button>
  </div>
  <div id="hint">Keys 1-5 select a language, Enter saves and advances.</div>

<script>
let state = null;
let selectedLang = null;

async function loadState(i) {
  const url = i === null ? "/api/state" : `/api/state?i=${i}`;
  const res = await fetch(url);
  state = await res.json();
  selectedLang = state.ground_truth_lang || null;
  render();
}

function render() {
  document.getElementById("progress").textContent =
    `Clip ${state.index + 1} / ${state.total} — ${state.done} labeled`;
  document.getElementById("meta").innerHTML =
    `duration: ${state.duration}s · source: ${state.source} · <a href="${state.yt_url}" target="_blank" rel="noopener">open on YouTube</a>`;
  document.getElementById("candidate").textContent = state.candidate_1 || "(no candidate transcription)";
  document.getElementById("notes").value = state.notes || "";
  document.querySelectorAll("#langs button").forEach(b => {
    b.classList.toggle("selected", b.dataset.lang === selectedLang);
  });
  const player = document.getElementById("player");
  player.src = `/audio/${state.clip_id}.wav`;
  player.play().catch(() => {});
  document.getElementById("prev").disabled = state.index === 0;
}

async function save(advance) {
  const notes = document.getElementById("notes").value;
  const res = await fetch("/api/label", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ index: state.index, clip_id: state.clip_id, lang: selectedLang || "", notes }),
  });
  const result = await res.json();
  if (result.error) { alert(result.error); return; }
  if (advance) {
    await loadState(result.next_index);
  } else {
    state.done = result.done;
    document.getElementById("progress").textContent =
      `Clip ${state.index + 1} / ${state.total} — ${state.done} labeled`;
  }
}

document.querySelectorAll("#langs button").forEach(b => {
  b.addEventListener("click", () => {
    selectedLang = b.dataset.lang;
    render();
  });
});
document.getElementById("save").addEventListener("click", () => save(true));
document.getElementById("prev").addEventListener("click", () => loadState(Math.max(0, state.index - 1)));

document.addEventListener("keydown", (e) => {
  if (document.activeElement.id === "notes") {
    if (e.key === "Enter") { e.preventDefault(); save(true); }
    return;
  }
  if (["1", "2", "3", "4", "5"].includes(e.key)) {
    selectedLang = ["ca", "es", "en", "other", "unsure"][Number(e.key) - 1];
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
            rows = load_rows()
            qs = parse_qs(parsed.query)
            idx = int(qs["i"][0]) if "i" in qs else first_unlabeled(rows)
            idx = max(0, min(idx, len(rows) - 1))
            row = rows[idx]
            done = sum(1 for r in rows if r["ground_truth_lang"])
            self._json({
                "index": idx,
                "total": len(rows),
                "done": done,
                "clip_id": row["clip_id"],
                "duration": row["duration"],
                "yt_url": row["yt_url"],
                "candidate_1": row["candidate_1"],
                "ground_truth_lang": row["ground_truth_lang"],
                "notes": row["notes"],
                "source": row.get("source", ""),
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
        if self.path != "/api/label":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length))
        rows = load_rows()
        idx = payload.get("index")
        clip_id = payload.get("clip_id")
        if idx is None or not (0 <= idx < len(rows)) or rows[idx]["clip_id"] != clip_id:
            self._json({"error": "index/clip_id mismatch — reload the page"}, status=409)
            return
        rows[idx]["ground_truth_lang"] = payload.get("lang", "")
        rows[idx]["notes"] = payload.get("notes", "")
        save_rows(rows)
        done = sum(1 for r in rows if r["ground_truth_lang"])
        next_idx = idx + 1 if idx + 1 < len(rows) else idx
        self._json({"saved": True, "done": done, "total": len(rows), "next_index": next_idx})

    def log_message(self, fmt, *args):
        pass  # quiet — local single-user tool


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()

    if not SAMPLE_TSV.exists():
        raise SystemExit(f"{SAMPLE_TSV} not found — run scripts/language_id/build_ground_truth.py first")

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Labeling UI at http://{args.host}:{args.port}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
