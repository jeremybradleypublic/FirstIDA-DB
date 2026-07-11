"""Render the dataset to a single self-contained, interactive HTML console you
open in a browser. It shows BOTH data sources (the git scraper AND the
generator) and has four tabs:

  • Pairs   — every (source, asm) pair, filterable by source system, route,
              session, language, and a full-text search; hybrid asm carries a
              `<symbol>:` header so it reads like the objdump-derived asm.
  • Journal — the live activity logs of both the scraper and the generator.
  • Sources — the list of git repos the scraper used (stars/license/n_pairs).
  • Graph   — the dbgraph knowledge graph, embedded.

  python -m pipeline.gallery                       # newest pairs from both sources
  python -m pipeline.gallery --route hybrid --limit 200
"""
import argparse
import html
import json
import os
import time

import pipeline.store as store

DEFAULT_OUT = "dataset/gallery.html"
_J_SCRAPER = "dataset/journal.jsonl"
_J_GEN = "dataset/journal-gen.jsonl"
_DBGRAPH_REL = "../db-graph/dbgraph.html"   # relative to dataset/gallery.html


def _source_system(origin):
    if origin == "harvest":
        return "git-scraper"
    if origin and origin.startswith("gen:"):
        return "generator"
    return origin or "unknown"


def _route(origin):
    if origin and origin.startswith("gen:"):
        return origin.split(":", 1)[1]
    return "—"


def _pair_dict(r):
    origin = r["origin"]
    ss, rt = _source_system(origin), _route(origin)
    asm = r["asm_text"] or ""
    # Give hybrid asm a `<symbol>:` header (older rows lack it) so it reads like
    # the direct/scraper objdump asm.
    if ss == "generator" and rt == "hybrid" and not asm.lstrip().startswith("<"):
        asm = f"<{r['func_name']}>:\n{asm}"
    return {"id": r["id"], "source_system": ss, "route": rt,
            "func_name": r["func_name"], "lang": r["lang"], "compiler": r["compiler"],
            "opt": r["opt_level"], "fmt": r["obj_format"], "session": r["session"],
            "signature": r["signature"], "source": r["source_text"] or "", "asm": asm}


def _fetch_pairs(conn, limit):
    """Newest rows from BOTH sources so each is browsable even though the scraper
    has vastly more rows than the generator."""
    per = max(1, limit // 2)
    gen = conn.execute("SELECT * FROM pairs WHERE origin LIKE 'gen:%' "
                       "ORDER BY id DESC LIMIT ?", (per,)).fetchall()
    harv = conn.execute("SELECT * FROM pairs WHERE origin='harvest' "
                        "ORDER BY id DESC LIMIT ?", (per,)).fetchall()
    return list(gen) + list(harv)


def _fetch_sessions(conn):
    rows = conn.execute(
        """SELECT session,
                  CASE WHEN origin='harvest' THEN 'git-scraper'
                       WHEN origin LIKE 'gen:%' THEN 'generator'
                       ELSE 'unknown' END AS ss,
                  COUNT(*) AS n
             FROM pairs WHERE session IS NOT NULL
            GROUP BY session, ss ORDER BY session DESC""").fetchall()
    return [{"session": r["session"], "source_system": r["ss"], "n": r["n"]} for r in rows]


def _fetch_sources(conn):
    try:
        rows = store.all_repos(conn)
    except Exception:
        return []
    return [{"url": r["url"], "status": r["status"], "stars": r["stars"],
             "license": r["license"], "n_pairs": r["n_pairs"], "commit": r["commit_sha"]}
            for r in rows]


def _load_journal(n=250):
    out = []
    for stream, path in (("scraper", _J_SCRAPER), ("generator", _J_GEN)):
        if not os.path.exists(path):
            continue
        try:
            lines = open(path, encoding="utf-8").read().splitlines()[-n:]
        except OSError:
            continue
        for ln in lines:
            try:
                e = json.loads(ln)
            except Exception:
                continue
            ts = e.get("ts", 0)
            hhmmss = time.strftime("%H:%M:%S", time.localtime(ts)) if ts else ""
            msg = e.get("argv") if e.get("kind") == "cmd" else e.get("msg", "")
            out.append({"stream": stream, "ts": hhmmss, "kind": e.get("kind", "event"),
                        "msg": msg or "", "level": e.get("level", "info")})
    return out


def _stats(conn):
    d = dict(conn.execute(
        """SELECT CASE WHEN origin='harvest' THEN 'git-scraper'
                       WHEN origin LIKE 'gen:%' THEN 'generator'
                       ELSE 'unknown' END, COUNT(*) FROM pairs GROUP BY 1""").fetchall())
    d["total"] = sum(d.values())
    return d


def build_gallery(db_path="dataset/pairs.db", out_path=DEFAULT_OUT, limit=400, route=None):
    conn = store.connect(db_path)
    store.init_schema(conn)
    store.migrate(conn)   # ensure origin/session columns + pairs_labeled view exist
    pairs = [_pair_dict(r) for r in _fetch_pairs(conn, limit)]
    if route:
        pairs = [p for p in pairs if p["route"] == route]
    data = {"pairs": pairs, "sessions": _fetch_sessions(conn),
            "sources": _fetch_sources(conn), "journal": _load_journal(),
            "stats": _stats(conn), "dbgraph": _DBGRAPH_REL}
    conn.close()
    # Embed as JSON; neutralise "</" so a source/asm containing "</script>" can
    # never break out of the <script> block.
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    stamp = time.strftime("%Y-%m-%d %H:%M")
    out = _HTML.replace("%%DATA%%", blob).replace("%%STAMP%%", html.escape(stamp))
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(out)
    return out_path


_HTML = r"""<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>FirstIDA-DB console</title>
<style>
:root{--bg:#fff;--fg:#1a1a1a;--dim:#6a737d;--card:#f6f8fa;--border:#e1e4e8;
 --srcbg:#f3faf3;--asmbg:#f2f5fc;--accent:#0969da;--scraper:#0969da;--generator:#8250df;
 --direct:#1a7f37;--hybrid:#8250df}
@media(prefers-color-scheme:dark){:root{--bg:#0d1117;--fg:#e6edf3;--dim:#8b949e;
 --card:#161b22;--border:#30363d;--srcbg:#0f1a0f;--asmbg:#0f1428;--accent:#58a6ff;
 --scraper:#58a6ff;--generator:#bc8cff;--direct:#3fb950;--hybrid:#bc8cff}}
:root[data-theme=dark]{--bg:#0d1117;--fg:#e6edf3;--dim:#8b949e;--card:#161b22;
 --border:#30363d;--srcbg:#0f1a0f;--asmbg:#0f1428;--accent:#58a6ff;--scraper:#58a6ff;
 --generator:#bc8cff;--direct:#3fb950;--hybrid:#bc8cff}
:root[data-theme=light]{--bg:#fff;--fg:#1a1a1a;--dim:#6a737d;--card:#f6f8fa;
 --border:#e1e4e8;--srcbg:#f3faf3;--asmbg:#f2f5fc;--accent:#0969da;--scraper:#0969da;
 --generator:#8250df;--direct:#1a7f37;--hybrid:#8250df}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
 font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
header{padding:16px 22px;border-bottom:1px solid var(--border);position:sticky;top:0;
 background:var(--bg);z-index:5}
h1{margin:0;font-size:19px}
.stats{color:var(--dim);font-size:13px;margin-top:2px}
.stats b{color:var(--fg)}
.tabs{display:flex;gap:4px;margin-top:12px}
.tab{padding:7px 16px;border:1px solid var(--border);border-bottom:none;border-radius:8px 8px 0 0;
 background:var(--card);cursor:pointer;font-size:13px;color:var(--dim)}
.tab.on{color:var(--accent);font-weight:600;border-color:var(--accent)}
.panel{display:none;padding:18px 22px}
.panel.on{display:block}
.bar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:14px}
select,input[type=text]{background:var(--card);color:var(--fg);border:1px solid var(--border);
 border-radius:7px;padding:6px 10px;font-size:13px}
input[type=text]{min-width:220px;flex:1}
.count{color:var(--dim);font-size:12px;margin-left:auto}
.card{border:1px solid var(--border);border-radius:10px;overflow:hidden;background:var(--card);margin-bottom:14px}
.chead{display:flex;align-items:center;gap:8px;padding:9px 13px;flex-wrap:wrap;border-bottom:1px solid var(--border)}
.name{font-family:ui-monospace,Menlo,monospace;font-weight:600}
.badge{font-size:11px;padding:2px 8px;border-radius:10px;border:1px solid var(--border);color:var(--dim)}
.badge.ss-git-scraper{color:var(--scraper);border-color:var(--scraper)}
.badge.ss-generator{color:var(--generator);border-color:var(--generator)}
.badge.route-direct{color:var(--direct);border-color:var(--direct)}
.badge.route-hybrid{color:var(--hybrid);border-color:var(--hybrid)}
.badge.sess{font-family:ui-monospace,Menlo,monospace}
.cols{display:grid;grid-template-columns:1fr 1fr}
@media(max-width:760px){.cols{grid-template-columns:1fr}}
.col h3{margin:0;font-size:11px;text-transform:uppercase;letter-spacing:.5px;color:var(--dim);
 padding:7px 13px;border-bottom:1px solid var(--border)}
pre{margin:0;padding:11px 13px;overflow-x:auto;font-family:ui-monospace,Menlo,monospace;
 font-size:12.5px;line-height:1.5;white-space:pre}
.col.src pre{background:var(--srcbg)}.col.asm pre{background:var(--asmbg);border-left:1px solid var(--border)}
.empty{color:var(--dim);padding:40px;text-align:center}
.jrow{display:flex;gap:10px;font-family:ui-monospace,Menlo,monospace;font-size:12.5px;padding:1px 0;
 border-bottom:1px solid transparent}
.jts{color:var(--dim)}
.jstream{padding:0 6px;border-radius:8px;font-size:11px}
.jstream.scraper{color:var(--scraper)}.jstream.generator{color:var(--generator)}
.jrow.warn .jmsg{color:#d29922}.jrow.error .jmsg{color:#f85149}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{text-align:left;padding:6px 10px;border-bottom:1px solid var(--border)}
th{color:var(--dim);font-weight:600;cursor:pointer;position:sticky;top:0;background:var(--bg)}
td a{color:var(--accent);text-decoration:none}
iframe{width:100%;height:78vh;border:1px solid var(--border);border-radius:10px;background:#fff}
.ghint{color:var(--dim);font-size:12px;margin-bottom:10px}
</style></head><body>
<header>
 <h1>FirstIDA-DB console</h1>
 <div class=stats id=stats></div>
 <div class=tabs>
   <div class="tab on" data-p=p-pairs>Pairs</div>
   <div class=tab data-p=p-journal>Journal</div>
   <div class=tab data-p=p-sources>Sources</div>
   <div class=tab data-p=p-graph>Graph</div>
 </div>
</header>

<div class="panel on" id=p-pairs>
 <div class=bar>
   <select id=f-source><option value="">all sources</option>
     <option value=git-scraper>git-scraper</option><option value=generator>generator</option></select>
   <select id=f-route><option value="">all routes</option>
     <option value=direct>direct</option><option value=hybrid>hybrid</option></select>
   <select id=f-session><option value="">all sessions</option></select>
   <input type=text id=f-q placeholder="search name or source…">
   <span class=count id=pairs-count></span>
 </div>
 <div id=pairs></div>
</div>

<div class=panel id=p-journal>
 <div class=bar>
   <select id=j-stream><option value="">both streams</option>
     <option value=scraper>scraper</option><option value=generator>generator</option></select>
   <span class=count id=j-count></span>
 </div>
 <div id=journal></div>
</div>

<div class=panel id=p-sources>
 <div class=ghint>Every git repo the scraper used (also stored in <code>dataset/sources_used.tsv</code>). Click a header to sort.</div>
 <table id=sources><thead><tr>
   <th data-k=url>repo</th><th data-k=status>status</th><th data-k=stars>stars</th>
   <th data-k=license>license</th><th data-k=n_pairs>pairs</th></tr></thead><tbody></tbody></table>
</div>

<div class=panel id=p-graph>
 <div class=ghint>dbgraph knowledge graph of the schema. If it doesn't load (browser file rules),
   <a id=graph-link target=_blank>open it in a new tab</a>.</div>
 <iframe id=graph-frame></iframe>
</div>

<script>
const DATA = %%DATA%%;
const $ = s => document.querySelector(s);
const el = (t,c,txt)=>{const e=document.createElement(t); if(c)e.className=c; if(txt!=null)e.textContent=txt; return e;};

// header stats
(function(){const s=DATA.stats;
 $('#stats').innerHTML='<b>'+(s.total||0).toLocaleString()+'</b> pairs · '+
   '<b>'+((s['git-scraper']||0)).toLocaleString()+'</b> git-scraper · '+
   '<b>'+((s.generator||0)).toLocaleString()+'</b> generator · '+
   DATA.sessions.length+' sessions · '+DATA.sources.length+' repos · built %%STAMP%%';})();

// tabs
document.querySelectorAll('.tab').forEach(t=>t.onclick=()=>{
 document.querySelectorAll('.tab').forEach(x=>x.classList.remove('on'));
 document.querySelectorAll('.panel').forEach(x=>x.classList.remove('on'));
 t.classList.add('on'); $('#'+t.dataset.p).classList.add('on');
 if(t.dataset.p==='p-graph') loadGraph();});

// sessions dropdown
DATA.sessions.forEach(s=>{const o=el('option'); o.value=s.session||'';
 o.textContent=(s.session||'(none)')+' · '+s.source_system+' ('+s.n+')'; $('#f-session').appendChild(o);});

function badge(head,t,cls){if(t==null||t===''||t==='—')return; head.appendChild(el('span','badge '+(cls||''),t));}
function pairMatches(p){
 const ss=$('#f-source').value,rt=$('#f-route').value,se=$('#f-session').value,q=$('#f-q').value.toLowerCase();
 if(ss&&p.source_system!==ss)return false;
 if(rt&&p.route!==rt)return false;
 if(se&&(p.session||'')!==se)return false;
 if(q&&!(p.func_name.toLowerCase().includes(q)||(p.source||'').toLowerCase().includes(q)))return false;
 return true;}
function renderPairs(){
 const box=$('#pairs'); box.innerHTML='';
 const shown=DATA.pairs.filter(pairMatches);
 $('#pairs-count').textContent=shown.length+' / '+DATA.pairs.length+' shown';
 if(!shown.length){box.appendChild(el('div','empty','No pairs match — adjust the filters, or run scripts/run_all.sh.'));return;}
 shown.forEach(p=>{
   const card=el('div','card'),head=el('div','chead');
   head.appendChild(el('span','name',p.func_name));
   badge(head,p.source_system,'ss-'+p.source_system);
   badge(head,p.route,'route-'+p.route);
   badge(head,p.lang);
   badge(head,p.compiler);
   if(p.opt&&p.opt!=='none')badge(head,p.opt);
   badge(head,p.session,'sess');
   card.appendChild(head);
   const cols=el('div','cols');
   const cs=el('div','col src'); cs.appendChild(el('h3',null,'source')); cs.appendChild(el('pre',null,p.source)); cols.appendChild(cs);
   const ca=el('div','col asm'); ca.appendChild(el('h3',null,'disassembly (X)')); ca.appendChild(el('pre',null,p.asm)); cols.appendChild(ca);
   card.appendChild(cols); box.appendChild(card);});
}
['#f-source','#f-route','#f-session','#f-q'].forEach(s=>{const e=$(s);e.oninput=renderPairs;e.onchange=renderPairs;});
renderPairs();

// journal
function renderJournal(){
 const box=$('#journal'); box.innerHTML=''; const f=$('#j-stream').value;
 const rows=DATA.journal.filter(j=>!f||j.stream===f);
 $('#j-count').textContent=rows.length+' entries';
 if(!rows.length){box.appendChild(el('div','empty','No journal entries yet.'));return;}
 rows.forEach(j=>{const r=el('div','jrow '+(j.level||''));
   r.appendChild(el('span','jts',j.ts));
   r.appendChild(el('span','jstream '+j.stream,j.stream));
   r.appendChild(el('span','jmsg',(j.kind==='cmd'?'$ ':'')+j.msg));
   box.appendChild(r);});}
$('#j-stream').onchange=renderJournal; renderJournal();

// sources
let sortK=null,sortDir=1;
function renderSources(){
 const tb=$('#sources tbody'); tb.innerHTML='';
 let rows=DATA.sources.slice();
 if(sortK)rows.sort((a,b)=>{let x=a[sortK],y=b[sortK]; if(x==null)x=''; if(y==null)y='';
   return (x>y?1:x<y?-1:0)*sortDir;});
 rows.forEach(r=>{const tr=el('tr');
   const td1=el('td'); const a=el('a',null,r.url); a.href=r.url; a.target='_blank'; td1.appendChild(a); tr.appendChild(td1);
   tr.appendChild(el('td',null,r.status||''));
   tr.appendChild(el('td',null,r.stars==null?'':String(r.stars)));
   tr.appendChild(el('td',null,r.license||''));
   tr.appendChild(el('td',null,r.n_pairs==null?'':String(r.n_pairs)));
   tb.appendChild(tr);});}
document.querySelectorAll('#sources th').forEach(th=>th.onclick=()=>{
 const k=th.dataset.k; sortDir=(sortK===k)?-sortDir:1; sortK=k; renderSources();});
renderSources();

// graph
let graphLoaded=false;
function loadGraph(){if(graphLoaded)return; graphLoaded=true;
 $('#graph-frame').src=DATA.dbgraph; $('#graph-link').href=DATA.dbgraph;}
</script></body></html>"""


def main():
    ap = argparse.ArgumentParser(description="Render the dataset to an interactive HTML console.")
    ap.add_argument("--db", default="dataset/pairs.db")
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--route", choices=("direct", "hybrid"), default=None,
                    help="only this generator route")
    ap.add_argument("--limit", type=int, default=400,
                    help="max pairs embedded (split across both sources)")
    args = ap.parse_args()
    out = build_gallery(args.db, args.out, limit=args.limit, route=args.route)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
