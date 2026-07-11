"""Render generated (source, asm) pairs to a self-contained HTML gallery you
open in a browser — the visual counterpart to the live journal. Pulls rows
from `dataset/pairs.db` (by default only the generator's rows, origin like
'gen:%') and lays each pair out source-on-the-left, asm-on-the-right.

  python -m pipeline.gallery                       # newest 300 generated pairs
  python -m pipeline.gallery --route hybrid --limit 100
  python -m pipeline.gallery --all --out /tmp/all.html   # include harvested rows
"""
import argparse
import html
import os

import pipeline.store as store

DEFAULT_OUT = "dataset/gallery.html"

_CSS = """
:root{--bg:#fff;--fg:#1a1a1a;--dim:#6a737d;--card:#f6f8fa;--border:#e1e4e8;
  --src:#0b3d0b;--asm:#0d1b3d;--srcbg:#f3faf3;--asmbg:#f2f5fc;
  --direct:#1a7f37;--hybrid:#8250df;--accent:#0969da}
@media (prefers-color-scheme:dark){:root{--bg:#0d1117;--fg:#e6edf3;--dim:#8b949e;
  --card:#161b22;--border:#30363d;--src:#7ee787;--asm:#a5b4fc;
  --srcbg:#0f1a0f;--asmbg:#0f1428;--direct:#3fb950;--hybrid:#bc8cff;--accent:#58a6ff}}
:root[data-theme=dark]{--bg:#0d1117;--fg:#e6edf3;--dim:#8b949e;--card:#161b22;
  --border:#30363d;--src:#7ee787;--asm:#a5b4fc;--srcbg:#0f1a0f;--asmbg:#0f1428;
  --direct:#3fb950;--hybrid:#bc8cff;--accent:#58a6ff}
:root[data-theme=light]{--bg:#fff;--fg:#1a1a1a;--dim:#6a737d;--card:#f6f8fa;
  --border:#e1e4e8;--src:#0b3d0b;--asm:#0d1b3d;--srcbg:#f3faf3;--asmbg:#f2f5fc;
  --direct:#1a7f37;--hybrid:#8250df;--accent:#0969da}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
  font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
header{padding:20px 24px;border-bottom:1px solid var(--border);position:sticky;top:0;
  background:var(--bg);z-index:2}
h1{margin:0 0 4px;font-size:20px}
.sub{color:var(--dim);font-size:13px}
.filters{margin-top:12px;display:flex;gap:8px;flex-wrap:wrap}
.chip{border:1px solid var(--border);background:var(--card);color:var(--fg);
  padding:5px 12px;border-radius:20px;cursor:pointer;font-size:13px}
.chip.on{border-color:var(--accent);color:var(--accent);font-weight:600}
main{padding:20px 24px;display:flex;flex-direction:column;gap:16px}
.card{border:1px solid var(--border);border-radius:10px;overflow:hidden;background:var(--card)}
.chead{display:flex;align-items:center;gap:10px;padding:10px 14px;flex-wrap:wrap;
  border-bottom:1px solid var(--border)}
.name{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-weight:600}
.badge{font-size:11px;padding:2px 8px;border-radius:10px;border:1px solid var(--border);
  color:var(--dim)}
.badge.route-direct{color:var(--direct);border-color:var(--direct)}
.badge.route-hybrid{color:var(--hybrid);border-color:var(--hybrid)}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:0}
@media (max-width:760px){.cols{grid-template-columns:1fr}}
.col{padding:0}
.col h3{margin:0;font-size:11px;text-transform:uppercase;letter-spacing:.5px;
  color:var(--dim);padding:8px 14px;border-bottom:1px solid var(--border)}
.col.src h3{color:var(--src)}.col.asm h3{color:var(--asm)}
pre{margin:0;padding:12px 14px;overflow-x:auto;font-family:ui-monospace,SFMono-Regular,
  Menlo,monospace;font-size:12.5px;line-height:1.5;white-space:pre}
.col.src pre{background:var(--srcbg)}.col.asm pre{background:var(--asmbg);
  border-left:1px solid var(--border)}
.empty{color:var(--dim);padding:40px;text-align:center}
"""

_JS = """
const chips=[...document.querySelectorAll('.chip')];
chips.forEach(c=>c.onclick=()=>{chips.forEach(x=>x.classList.remove('on'));
  c.classList.add('on');const f=c.dataset.f;
  document.querySelectorAll('.card').forEach(card=>{
    card.style.display=(f==='all'||card.dataset.route===f)?'':'none';});});
"""


def _rows(conn, origin_like, limit):
    return conn.execute(
        """SELECT origin, func_name, lang, compiler, opt_level, obj_format,
                  signature, source_text, asm_text
             FROM pairs WHERE origin LIKE ? ORDER BY id DESC LIMIT ?""",
        (origin_like, limit)).fetchall()


def _route(origin):
    return origin.split(":", 1)[1] if origin and ":" in origin else (origin or "?")


def render_html(rows) -> str:
    e = html.escape
    counts = {}
    for r in rows:
        counts[_route(r["origin"])] = counts.get(_route(r["origin"]), 0) + 1
    summary = " · ".join(f"{v} {k}" for k, v in sorted(counts.items())) or "none"

    chips = ['<span class="chip on" data-f="all">all</span>']
    for k in sorted(counts):
        chips.append(f'<span class="chip" data-f="{e(k)}">{e(k)} ({counts[k]})</span>')

    cards = []
    for r in rows:
        route = _route(r["origin"])
        badges = [f'<span class="badge route-{e(route)}">{e(route)}</span>',
                  f'<span class="badge">{e(r["lang"])}</span>']
        if r["compiler"]:
            badges.append(f'<span class="badge">{e(r["compiler"])}</span>')
        if r["opt_level"] and r["opt_level"] != "none":
            badges.append(f'<span class="badge">{e(r["opt_level"])}</span>')
        badges.append(f'<span class="badge">{e(r["obj_format"] or "")}</span>')
        cards.append(
            f'<div class="card" data-route="{e(route)}">'
            f'<div class="chead"><span class="name">{e(r["func_name"])}</span>'
            + "".join(badges) + "</div>"
            '<div class="cols">'
            f'<div class="col src"><h3>source</h3><pre>{e(r["source_text"] or "")}</pre></div>'
            f'<div class="col asm"><h3>disassembly</h3><pre>{e(r["asm_text"] or "")}</pre></div>'
            "</div></div>")

    body = "".join(cards) or '<div class="empty">No generated pairs yet — run scripts/generate.sh first.</div>'
    return (
        "<!doctype html><html><head><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width,initial-scale=1'>"
        "<title>disasmgen — generated pairs</title>"
        f"<style>{_CSS}</style></head><body>"
        f"<header><h1>disasmgen — generated function pairs</h1>"
        f"<div class=sub>{e(str(len(rows)))} shown · {e(summary)}</div>"
        f"<div class=filters>{''.join(chips)}</div></header>"
        f"<main>{body}</main><script>{_JS}</script></body></html>")


def build_gallery(db_path="dataset/pairs.db", out_path=DEFAULT_OUT,
                  origin_like="gen:%", limit=300):
    """Query pairs.db and write a self-contained HTML gallery. Returns out_path."""
    conn = store.connect(db_path)
    rows = _rows(conn, origin_like, limit)
    conn.close()
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(render_html(rows))
    return out_path


def main():
    ap = argparse.ArgumentParser(description="Render generated pairs to an HTML gallery.")
    ap.add_argument("--db", default="dataset/pairs.db")
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--route", choices=("direct", "hybrid"), default=None,
                    help="only this generator route (default: all generated)")
    ap.add_argument("--all", action="store_true",
                    help="include harvested rows too, not just generated")
    ap.add_argument("--limit", type=int, default=300)
    args = ap.parse_args()
    origin_like = "%" if args.all else (f"gen:{args.route}" if args.route else "gen:%")
    out = build_gallery(args.db, args.out, origin_like=origin_like, limit=args.limit)
    n = 0
    conn = store.connect(args.db)
    n = conn.execute("SELECT COUNT(*) FROM pairs WHERE origin LIKE ?",
                     (origin_like,)).fetchone()[0]
    conn.close()
    print(f"wrote {out}  ({min(n, args.limit)} of {n} matching pairs)")


if __name__ == "__main__":
    main()
