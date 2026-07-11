"""Generator ingest driver: runs the native `disasmgen` binary, validates its
JSONL against the frozen record schema, and ingests pairs into the SAME
dataset/pairs.db as the harvester — tagged origin='gen:direct'/'gen:hybrid'.

Runs in PARALLEL with the harvester: its own journal file
(dataset/journal-gen.jsonl, viewable with
`scripts/journal.sh --path dataset/journal-gen.jsonl -f`), its own dashboard
window (scripts/generate.sh), and a shared WAL DB serialized by busy_timeout.

Frozen JSONL record schema (the contract with generator/):
  common:  route ("direct"|"hybrid"), func_name, lang ("c"|"cpp"),
           signature, source_text, seed (int)
  hybrid adds: asm_text, obj_format ("rawx86_64"), compiler ("asmjit"),
           opt_level ("none")
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys

import pipeline.store as store
import pipeline.run_pipeline as run_pipeline
from pipeline.journal import Journal

HOME = os.path.expanduser("~")
# MUST be under $HOME — Colima only virtiofs-mounts the home dir, so a scratch
# repo anywhere else mounts as an empty /src inside the toolchain container
# (same constraint as harvest.SCRATCH_ROOT).
SCRATCH_ROOT = os.path.join(HOME, ".cache", "disasm_generate")
JOURNAL_PATH = "dataset/journal-gen.jsonl"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.join(ROOT, "generator", "build", "disasmgen")
GRAPH_SH = os.path.join(ROOT, "scripts", "build_graph.sh")

REQUIRED_COMMON = ("route", "func_name", "lang", "signature", "source_text", "seed")
REQUIRED_HYBRID = ("asm_text", "obj_format", "compiler", "opt_level")
# func_name becomes a scratch filename in the direct route — keep it to a safe
# identifier so a hostile/garbled record can never escape the scratch dir.
_SAFE_NAME = re.compile(r"^[A-Za-z0-9_]+$")


def parse_records(jsonl_text, journal=None):
    """Validate JSONL against the frozen record schema. A malformed or
    incomplete line is skipped with a journal warning — never fatal."""
    records = []
    for i, line in enumerate(jsonl_text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            if journal:
                journal.event(f"malformed JSONL line {i}: not JSON — skipped",
                              level="warn")
            continue
        if not isinstance(rec, dict) or rec.get("route") not in ("direct", "hybrid"):
            if journal:
                journal.event(f"invalid record line {i}: bad route — skipped",
                              level="warn")
            continue
        required = REQUIRED_COMMON + (
            REQUIRED_HYBRID if rec["route"] == "hybrid" else ())
        missing = [k for k in required if k not in rec]
        if missing:
            if journal:
                journal.event(f"invalid record line {i}: missing {missing} — skipped",
                              level="warn")
            continue
        if not _SAFE_NAME.match(str(rec["func_name"])):
            if journal:
                journal.event(f"invalid record line {i}: unsafe func_name "
                              f"{rec['func_name']!r} — skipped", level="warn")
            continue
        records.append(rec)
    return records


def ingest_hybrid(conn, records, journal=None):
    """Insert full hybrid pairs as-is (no compile step). Dedup collisions are
    counted, not errors (existing INSERT OR IGNORE via pair_hash)."""
    stats = {"pairs": 0, "dedup": 0}
    for rec in records:
        ok = store.insert_pair(
            conn, repo="gen:hybrid",
            file_path=f"gen/hybrid/{rec['func_name']}.c",
            func_name=rec["func_name"], signature=rec["signature"],
            lang=rec["lang"], arch="x86_64", opt_level="none",
            obj_format="rawx86_64", compiler="asmjit",
            source_text=rec["source_text"], asm_text=rec["asm_text"],
            origin="gen:hybrid")
        stats["pairs" if ok else "dedup"] += 1
    if journal:
        journal.event(f"hybrid ingest: {stats['pairs']} pairs, "
                      f"{stats['dedup']} dedup")
    return stats


def write_direct_repo(records, scratch_root=SCRATCH_ROOT):
    """Write every synthesized function as its own translation unit inside ONE
    scratch 'repo' dir under $HOME (Colima mount constraint), replacing any
    previous batch. Returns the repo dir path."""
    assert scratch_root.startswith(HOME + os.sep), "scratch root must be under $HOME"
    dest = os.path.join(scratch_root, "batch")
    shutil.rmtree(dest, ignore_errors=True)
    os.makedirs(dest)
    for rec in records:
        ext = ".c" if rec["lang"] == "c" else ".cpp"
        path = os.path.join(dest, rec["func_name"] + ext)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(rec["source_text"])
    return dest


def ingest_direct(records, db_path, emit=lambda e: None, journal=None):
    """Compile synthesized sources through the EXISTING pipeline path
    (env -> compile -> disasm -> pair). tree-sitter re-extracts the function
    names from the written TUs, so pairing round-trips. Rows land with
    origin='gen:direct'; compile failures go to the existing `skipped` table
    and never abort the run."""
    if not records:
        return {"pairs": 0, "skipped": 0, "files": 0}
    dest = write_direct_repo(records)
    try:
        return run_pipeline.run(
            dest, repo="gen:direct", db_path=db_path,
            progress=lambda e: emit({**e, "repo": "gen:direct"}),
            journal=journal, origin="gen:direct")
    finally:
        shutil.rmtree(dest, ignore_errors=True)


def run_generator(route, count, seed, journal):
    """Run the native generator via journal.run so its stderr progress/skip
    lines stream into the dashboard mini-box, while the JSONL itself lands
    clean in a --out temp file (journal.run merges stderr into stdout, so
    capturing JSONL from stdout would interleave)."""
    if not (os.path.isfile(BIN) and os.access(BIN, os.X_OK)):
        raise RuntimeError(
            f"{BIN} not found — build it with: cmake -S generator -B "
            f"generator/build && cmake --build generator/build "
            f"(scripts/generate.sh does this automatically)")
    os.makedirs(SCRATCH_ROOT, exist_ok=True)
    out_path = os.path.join(SCRATCH_ROOT, f"{route}.jsonl")
    rc, _ = journal.run([BIN, route, "--count", str(count),
                         "--seed", str(seed), "--out", out_path])
    if rc != 0:
        raise RuntimeError(f"disasmgen {route} failed (rc={rc})")
    with open(out_path, encoding="utf-8") as fh:
        text = fh.read()
    os.remove(out_path)
    return parse_records(text, journal=journal)


def generate(count=100, route="both", db_path="dataset/pairs.db", seed=0,
             emit=lambda e: None):
    """Run the selected route(s) and ingest into db_path. Returns totals."""
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    conn = store.connect(db_path)
    store.init_schema(conn)
    store.migrate(conn)
    journal = Journal(path=JOURNAL_PATH, emit=emit)
    totals = {"pairs": 0, "skipped": 0, "dedup": 0}
    try:
        journal.event(f"generate start (route={route}, count={count}, seed={seed})")
        routes = ("direct", "hybrid") if route == "both" else (route,)
        for i, r in enumerate(routes):
            emit({"type": "stage", "repo": f"gen:{r}", "stage": "generating"})
            records = run_generator(r, count, seed, journal)
            journal.event(f"{r}: {len(records)} record(s) from generator")
            if r == "hybrid":
                st = ingest_hybrid(conn, records, journal=journal)
                totals["pairs"] += st["pairs"]
                totals["dedup"] += st["dedup"]
                emit({"type": "repo_done", "repo": "gen:hybrid", "status": "done",
                      "pairs": st["pairs"], "skipped": st["dedup"]})
            else:
                emit({"type": "stage", "repo": "gen:direct", "stage": "compiling"})
                st = ingest_direct(records, db_path, emit=emit, journal=journal)
                totals["pairs"] += st["pairs"]
                totals["skipped"] += st["skipped"]
                emit({"type": "repo_done", "repo": "gen:direct", "status": "done",
                      "pairs": st["pairs"], "skipped": st["skipped"]})
            emit({"type": "progress", "processed": i + 1})
        journal.event(f"generate finished: {totals['pairs']} pairs, "
                      f"{totals['skipped']} skipped, {totals['dedup']} dedup")
        return totals
    finally:
        conn.close()
        journal.close()


def refresh_graph():
    """Refresh the dbgraph knowledge graph after a run. `origin` is now a
    queryable dimension of the dataset graph (see db-graph/README.md)."""
    if not os.path.exists(GRAPH_SH):
        return
    subprocess.run(["bash", GRAPH_SH, "--structural-only"], check=False)


def _plain(e):
    t = e.get("type")
    if t == "repo_done":
        print(f"[{e.get('status')}] {e.get('repo')}  pairs={e.get('pairs', 0)} "
              f"skipped={e.get('skipped', 0)}")
    elif t == "stage" and e.get("repo"):
        print(f"  {e['stage']}: {e['repo']}")
    elif t == "log":
        print(f"  ({e.get('level')}) {e.get('msg')}")


def main():
    ap = argparse.ArgumentParser(
        description="Generate synthetic (asm, source) pairs via disasmgen.")
    ap.add_argument("--count", type=int, default=100, help="functions per route")
    ap.add_argument("--route", choices=("direct", "hybrid", "both"),
                    default="both")
    ap.add_argument("--db", default="dataset/pairs.db")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--no-dashboard", action="store_true",
                    help="plain line logging (CI/tests)")
    args = ap.parse_args()

    def work(emit):
        return generate(count=args.count, route=args.route, db_path=args.db,
                        seed=args.seed, emit=emit)

    if args.no_dashboard:
        totals = work(_plain)
    else:
        try:
            import pipeline.dashboard as dashboard
        except ImportError:
            print("rich not installed; falling back to plain logging "
                  "(pip install rich)", file=sys.stderr)
            totals = work(_plain)
        else:
            totals = dashboard.run_with_dashboard(work, limit=args.count)
    print(f"pairs={totals['pairs']} skipped={totals['skipped']} "
          f"dedup={totals['dedup']}")
    refresh_graph()


if __name__ == "__main__":
    main()
