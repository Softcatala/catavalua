#!/usr/bin/env python3
"""
Builds scripts/reference/town_dialects.tsv — a town -> comarca -> territori -> dialecte
gazetteer covering the whole Catalan-speaking domain (Països Catalans + Alguer).

Run once (or re-run if Wikipedia's municipi lists change):

    python scripts/build_town_dialects.py

Output lives in scripts/reference/ (not scripts/data/ — that name collides
with the .gitignore rule for the runtime data/ directory).

Sources (Catalan Wikipedia raw wikitext):
  - Llista de municipis de Catalunya
  - Llista de comunes de la Catalunya del Nord
  - Llista de municipis de les Illes Balears
  - Llista dels municipis del País Valencià (includes a "predomini lingüístic"
    C/V column per municipi, so no separate comarca->dialecte map is needed there)
  - Franja de Ponent comarca articles (Baix Cinca, Llitera, Matarranya, Baixa
    Ribagorça) + their Plantilla:Taula:* municipi-list templates — hand-curated
    below since no single list page enumerates the Franja's Catalan-speaking
    municipis with sources reliable enough to parse automatically.

dialecte values match the vocabulary used in scripts/transcribe.py's Gemini
prompt: central | valencian | balearic | northwestern | alguerès | septentrional
| unknown ("unknown" also covers places outside the Catalan-speaking domain,
e.g. Vall d'Aran (Aranese/Occitan) or historically Castilian-speaking parts of
the País Valencià).

Comarca -> dialecte assignment follows the standard IEC/GEC dialect
classification described on ca.wikipedia.org/wiki/Dialectes_del_català and the
dedicated "Català nord-occidental" / "Català oriental central" articles.
"""
import csv
import re
import sys
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

WIKI_RAW = "https://ca.wikipedia.org/w/index.php?title={}&action=raw"
CACHE_DIR = Path(__file__).parent / "reference" / ".wiki_cache"
OUT_PATH = Path(__file__).parent / "reference" / "town_dialects.tsv"


def fetch_wikitext(title: str) -> str:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / (re.sub(r"[^\w\-]", "_", title) + ".txt")
    if cache_file.exists():
        return cache_file.read_text(encoding="utf-8")
    url = WIKI_RAW.format(urllib.parse.quote(title))
    req = urllib.request.Request(url, headers={"User-Agent": "catvoice-gazetteer/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        text = resp.read().decode("utf-8")
    if text.lstrip().startswith("#REDIR"):
        redirect_title = re.search(r"\[\[([^\]|#]+)", text).group(1)
        return fetch_wikitext(redirect_title)
    cache_file.write_text(text, encoding="utf-8")
    return text


# ---------------------------------------------------------------------------
# Wikitext table parsing helpers
# ---------------------------------------------------------------------------

def table_rows(text, min_cols):
    """Split a `{| ... |- ... |}` wikitable into rows of '|'-prefixed cell
    lines. Handles both one-cell-per-line tables and single-line rows using
    '||' cell separators (normalize_inline_pipes below)."""
    for block in text.split("|-"):
        lines = [
            l.strip()
            for l in block.strip().splitlines()
            if l.strip().startswith("|") and not l.strip().startswith("|}")
        ]
        if len(lines) >= min_cols:
            yield lines


def normalize_inline_pipes(text):
    """Some wikitables put every cell of a row on one line, separated by
    '||', instead of one cell per line. Turn '||' into a cell-per-line
    boundary so table_rows can treat both formats the same."""
    return text.replace("||", "\n|")


def link_target(cell):
    m = re.search(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]", cell)
    if m:
        return m.group(1).strip()
    return re.sub(r"^\|+\s*", "", cell).strip()


def link_alias(cell):
    """Display text of a [[target|alias]] link, falling back to the target."""
    m = re.search(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]", cell)
    if m:
        return (m.group(2) or m.group(1)).strip()
    return re.sub(r"^\|+\s*", "", cell).strip()


rows = []  # (town, comarca, territori, dialecte, notes)

# ---------------------------------------------------------------------------
# Comarca -> dialecte for Catalunya (43 comarques as they appear in the
# municipis-de-Catalunya wikitable). Confirmed against "Català nord-occidental"
# (lists Alta Ribagorça, Pallars Jussà, Pallars Sobirà, Alt Urgell, Segarra,
# Noguera, Segrià, Urgell, Pla d'Urgell, Garrigues, Ribera d'Ebre, Priorat as
# core NW, Terra Alta/Baix Ebre/Montsià as NW-transition-to-Valencian, and
# Solsonès as part of the NW-to-Oriental transition strip that's "clarament
# nord-occidental"). Vall d'Aran speaks Aranese (Occitan), not Catalan.
# ---------------------------------------------------------------------------
CATALUNYA_COMARCA_DIALECT = {
    "Alta Ribagorça": "northwestern",
    "Pallars Jussà": "northwestern",
    "Pallars Sobirà": "northwestern",
    "Alt Urgell": "northwestern",
    "Segarra": "northwestern",
    "Noguera": "northwestern",
    "Segrià": "northwestern",
    "Urgell": "northwestern",
    "Pla d'Urgell": "northwestern",
    "Garrigues": "northwestern",
    "Ribera d'Ebre": "northwestern",
    "Priorat": "northwestern",
    "Terra Alta": "northwestern",
    "Baix Ebre": "northwestern",
    "Montsià": "northwestern",
    "Solsonès": "northwestern",
    "Barcelonès": "central",
    "Baix Llobregat": "central",
    "Vallès Occidental": "central",
    "Vallès Oriental": "central",
    "Maresme": "central",
    "Bages": "central",
    "Anoia": "central",
    "Osona": "central",
    "Berguedà": "central",
    "Moianès": "central",
    "Lluçanès": "central",
    "Baixa Cerdanya": "central",
    "Garraf": "central",
    "Alt Penedès": "central",
    "Baix Penedès": "central",
    "Tarragonès": "central",
    "Alt Camp": "central",
    "Baix Camp": "central",
    "Conca de Barberà": "central",
    "Selva": "central",
    "Gironès": "central",
    "Pla de l'Estany": "central",
    "Garrotxa": "central",
    "Baix Empordà": "central",
    "Alt Empordà": "central",
    "Ripollès": "central",
    "Vall d'Aran": "unknown",  # Aranese, not Catalan
}
CATALUNYA_NOTES = {
    "Vall d'Aran": "Aranès (occità) hi és la llengua pròpia, no català",
}

# ---------------------------------------------------------------------------
# Catalunya
# ---------------------------------------------------------------------------
text = fetch_wikitext("Llista de municipis de Catalunya")
for lines in table_rows(text, 5):
    municipi = link_target(lines[2])
    comarca = link_target(lines[3])
    dialecte = CATALUNYA_COMARCA_DIALECT.get(comarca, "unknown")
    notes = CATALUNYA_NOTES.get(comarca, "")
    rows.append((municipi, comarca, "Catalunya", dialecte, notes))

# ---------------------------------------------------------------------------
# Catalunya Nord — all comarques speak septentrional (rossellonès)
# ---------------------------------------------------------------------------
text = normalize_inline_pipes(fetch_wikitext("Llista de comunes de la Catalunya del Nord"))
for lines in table_rows(text, 2):
    municipi = link_target(lines[0])
    comarca = link_target(lines[1])
    rows.append((municipi, comarca, "Catalunya Nord", "septentrional", ""))

# ---------------------------------------------------------------------------
# Illes Balears — illa stands in for comarca; whole archipelago is balearic
# ---------------------------------------------------------------------------
text = normalize_inline_pipes(fetch_wikitext("Llista de municipis de les Illes Balears"))
for lines in table_rows(text, 2):
    municipi = link_target(lines[0])
    illa = link_target(lines[1])
    rows.append((municipi, illa, "Illes Balears", "balearic", ""))

# ---------------------------------------------------------------------------
# País Valencià — the wikitable already records "Predomini lingüístic" (C/V)
# per municipi: PL=V means Valencian-speaking (dialecte=valencian), PL=C means
# historically Castilian-speaking (not part of the Catalan-speaking domain).
# Row layout varies (some rows colspan the first two columns), so columns are
# located by walking back from the always-present "Prv" (província) cell.
# ---------------------------------------------------------------------------
text = fetch_wikitext("Llista dels municipis del País Valencià")
for lines in table_rows(text, 11):
    prv_idx = None
    for i in range(len(lines) - 1, -1, -1):
        if re.search(r"\[\[Prov[ií]ncia", lines[i], re.IGNORECASE) or re.match(r"^\|\s*\[\[[VAC]\]\]\s*$", lines[i]):
            prv_idx = i
            break
    if prv_idx is None:
        continue
    comarca_idx = prv_idx - 1
    pl_idx = comarca_idx - 1
    municipi = link_target(lines[0])
    comarca = link_target(lines[comarca_idx])
    pl = link_alias(lines[pl_idx])
    dialecte = "valencian" if pl.strip().upper() == "V" else "unknown"
    notes = "" if dialecte == "valencian" else "zona històricament castellanoparlant del País Valencià"
    rows.append((municipi, comarca, "País Valencià", dialecte, notes))

# ---------------------------------------------------------------------------
# Franja de Ponent — comarques aragoneses de parla catalana. No single
# Wikipedia list page enumerates just the Catalan-speaking municipis reliably,
# so this is hand-curated from the "Baix Cinca"/"Llitera"/"Matarranya"/"Baixa
# Ribagorça" comarca articles and their Plantilla:Taula:* municipi tables.
# ---------------------------------------------------------------------------
FRANJA = [
    # Baix Cinca: the comarca article explicitly names only these 5 of the
    # comarca's 11 municipis as Catalan-speaking; the rest are Aragonese.
    ("Fraga", "Baix Cinca", "northwestern", ""),
    ("Mequinensa", "Baix Cinca", "northwestern", ""),
    ("Saidí", "Baix Cinca", "northwestern", ""),
    ("Torrent de Cinca", "Baix Cinca", "northwestern", ""),
    ("Vilella de Cinca", "Baix Cinca", "northwestern", ""),
    ("Bellver de Cinca", "Baix Cinca", "unknown", "aragonesòfon"),
    ("Campdàsens", "Baix Cinca", "unknown", "aragonesòfon"),
    ("Ontinyena", "Baix Cinca", "unknown", "aragonesòfon"),
    ("Ossó de Cinca", "Baix Cinca", "unknown", "aragonesòfon"),
    ("Vallobar", "Baix Cinca", "unknown", "aragonesòfon"),
    ("Xalamera", "Baix Cinca", "unknown", "aragonesòfon"),
    # La Llitera: official comarca's 14 municipis; a handful have mixed or
    # uncertain language per the comarca article (flagged in notes rather
    # than excluded).
    ("Albelda", "Llitera", "northwestern", ""),
    ("Baells", "Llitera", "northwestern", ""),
    ("Binèfar", "Llitera", "northwestern", "capital comarcal, tradicionalment de parla més castellanitzada"),
    ("el Campell", "Llitera", "northwestern", ""),
    ("Camporrells", "Llitera", "northwestern", ""),
    ("Castellonroi", "Llitera", "northwestern", ""),
    ("Esplucs", "Llitera", "northwestern", "alguns nuclis de llengua incerta"),
    ("Peralta i Calassanç", "Llitera", "northwestern", ""),
    ("Sant Esteve de Llitera", "Llitera", "northwestern", ""),
    ("Sanui i Alins", "Llitera", "northwestern", "Sanui catalanòfon, Alins aragonòfon"),
    ("Tamarit de Llitera", "Llitera", "northwestern", ""),
    ("el Torricó", "Llitera", "northwestern", ""),
    ("Valldellou", "Llitera", "northwestern", ""),
    ("Vensilló", "Llitera", "northwestern", "llengua vehicular no assegurada"),
    # Matarranya (18 municipis, comarca oficial)
    ("Arenys de Lledó", "Matarranya", "northwestern", ""),
    ("Beseit", "Matarranya", "northwestern", ""),
    ("Calaceit", "Matarranya", "northwestern", ""),
    ("Fondespatla", "Matarranya", "northwestern", ""),
    ("Fórnols de Matarranya", "Matarranya", "northwestern", ""),
    ("la Freixneda", "Matarranya", "northwestern", ""),
    ("Lledó d'Algars", "Matarranya", "northwestern", ""),
    ("Massalió", "Matarranya", "northwestern", ""),
    ("Mont-roig de Tastavins", "Matarranya", "northwestern", ""),
    ("Pena-roja", "Matarranya", "northwestern", ""),
    ("la Portellada", "Matarranya", "northwestern", ""),
    ("Ràfels", "Matarranya", "northwestern", ""),
    ("Queretes", "Matarranya", "northwestern", ""),
    ("Torredarques", "Matarranya", "northwestern", ""),
    ("la Torre del Comte", "Matarranya", "northwestern", ""),
    ("la Vall de Tormo", "Matarranya", "northwestern", ""),
    ("Vall-de-roures", "Matarranya", "northwestern", ""),
    ("Valljunquera", "Matarranya", "northwestern", ""),
    # Baixa Ribagorça — catalanòfon towns named explicitly in the comarca
    # article's "postura nacional" definition (municipis only partly
    # Catalan-speaking, like Graus and Capella, are omitted here).
    ("Benavarri", "Ribagorça", "northwestern", ""),
    ("Tolba", "Ribagorça", "northwestern", ""),
    ("Viacamp i Lliterà", "Ribagorça", "northwestern", ""),
    ("Estopanyà", "Ribagorça", "northwestern", ""),
    ("Castigaleu", "Ribagorça", "northwestern", ""),
    ("Monesma i Queixigar", "Ribagorça", "northwestern", ""),
    ("Lasquarri", "Ribagorça", "northwestern", ""),
    ("Isàvena", "Ribagorça", "northwestern", ""),
    ("Beranui", "Ribagorça", "northwestern", ""),
    ("Tor-la-ribera", "Ribagorça", "northwestern", ""),
]
for municipi, comarca, dialecte, notes in FRANJA:
    rows.append((municipi, comarca, "Franja de Ponent", dialecte, notes))

# ---------------------------------------------------------------------------
# Andorra — 7 parròquies, dialecte andorrà (subdialecte del nord-occidental)
# ---------------------------------------------------------------------------
for parroquia in [
    "Andorra la Vella",
    "Canillo",
    "Encamp",
    "Escaldes-Engordany",
    "la Massana",
    "Ordino",
    "Sant Julià de Lòria",
]:
    rows.append((parroquia, parroquia, "Andorra", "northwestern", "parròquia"))

# ---------------------------------------------------------------------------
# L'Alguer — single town, Sardenya (Itàlia)
# ---------------------------------------------------------------------------
rows.append(("L'Alguer", "L'Alguer", "Alguer", "alguerès", ""))

# ---------------------------------------------------------------------------
# Write TSV
# ---------------------------------------------------------------------------
rows.sort(key=lambda r: (r[2], r[1], r[0]))
OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
with OUT_PATH.open("w", newline="", encoding="utf-8") as f:
    w = csv.writer(f, delimiter="\t")
    w.writerow(["town", "comarca", "territori", "dialecte", "notes"])
    w.writerows(rows)

print(f"wrote {len(rows)} rows to {OUT_PATH}", file=sys.stderr)
print(Counter(r[3] for r in rows), file=sys.stderr)
print(Counter(r[2] for r in rows), file=sys.stderr)
