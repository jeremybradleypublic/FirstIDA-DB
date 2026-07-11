"""Phase-2 harvester: drain the `repos` ledger — for each repo, shallow-clone
under $HOME, run the pipeline, record the outcome, and delete the checkout.
Disk stays flat; failures never abort the sweep; resumable via the ledger."""
import argparse
import os
import shutil
import signal
import subprocess
import sys

import pipeline.store as store
import pipeline.scrape as scrape
import pipeline.run_pipeline as run_pipeline

# MUST be under $HOME — Colima only virtiofs-mounts the home dir, so a checkout
# anywhere else mounts as an empty /src inside the toolchain container.
HOME = os.path.expanduser("~")
SCRATCH_ROOT = os.path.join(HOME, ".cache", "disasm_harvest")

_MIN_FREE_GB = 5.0
_MAX_REPO_MB = 500.0
_CLONE_TIMEOUT_S = 300

_stop = {"soft": False}


def _install_signals():
    def handler(signum, frame):
        if not _stop["soft"]:
            _stop["soft"] = True   # finish current repo, then stop
        else:
            raise KeyboardInterrupt  # second Ctrl-C: abort current repo
    signal.signal(signal.SIGINT, handler)


def _clone(url, dest):
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    try:
        r = subprocess.run(["git", "clone", "--depth", "1", "--single-branch", url, dest],
                           capture_output=True, text=True, timeout=_CLONE_TIMEOUT_S, env=env)
    except subprocess.TimeoutExpired:
        return False, "clone timeout"
    return r.returncode == 0, (r.stderr or "").strip()[:180]


def _commit_sha(dest):
    r = subprocess.run(["git", "-C", dest, "rev-parse", "HEAD"], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def _dir_size_mb(path):
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total / 1e6


def _repo_name(url):
    return "/".join(url.rstrip("/").split("/")[-2:])


def process_one(conn, row, db_path, emit):
    repo_id, url = row["id"], row["url"]
    name = _repo_name(url)
    dest = os.path.join(SCRATCH_ROOT, name.replace("/", "__"))
    shutil.rmtree(dest, ignore_errors=True)
    try:
        free_gb = shutil.disk_usage(SCRATCH_ROOT).free / 1e9
        if free_gb < _MIN_FREE_GB:
            emit({"type": "log", "level": "warn", "msg": f"low disk {free_gb:.1f}GB — skipping {name}"})
            store.mark_repo(conn, repo_id, "failed", reason=f"low disk {free_gb:.1f}GB")
            emit({"type": "repo_done", "repo": name, "status": "failed", "reason": "low disk"})
            return

        emit({"type": "stage", "repo": name, "stage": "cloning"})
        ok, err = _clone(url, dest)
        if not ok:
            store.mark_repo(conn, repo_id, "failed", reason=f"clone: {err}")
            emit({"type": "repo_done", "repo": name, "status": "failed", "reason": "clone"})
            return

        sha = _commit_sha(dest)
        size_mb = _dir_size_mb(dest)
        if size_mb > _MAX_REPO_MB:
            store.mark_repo(conn, repo_id, "failed", reason=f"too large {size_mb:.0f}MB")
            emit({"type": "repo_done", "repo": name, "status": "failed", "reason": "too large"})
            return

        emit({"type": "stage", "repo": name, "stage": "compiling"})
        stats = run_pipeline.run(dest, repo=name, db_path=db_path,
                                 progress=lambda e: emit({**e, "repo": name}))
        store.mark_repo(conn, repo_id, "done", n_pairs=stats["pairs"], commit_sha=sha)
        emit({"type": "repo_done", "repo": name, "status": "done",
              "pairs": stats["pairs"], "skipped": stats["skipped"]})
    except KeyboardInterrupt:
        store.mark_repo(conn, repo_id, "queued")   # let it be retried
        raise
    except Exception as e:  # one bad repo never kills the sweep
        store.mark_repo(conn, repo_id, "failed", reason=str(e)[:180])
        emit({"type": "repo_done", "repo": name, "status": "failed", "reason": str(e)[:50]})
    finally:
        shutil.rmtree(dest, ignore_errors=True)


def harvest(db_path="dataset/pairs.db", limit=None, emit=lambda e: None,
            discover_first=True, target=50):
    assert SCRATCH_ROOT.startswith(HOME + os.sep), "scratch root must be under $HOME"
    os.makedirs(SCRATCH_ROOT, exist_ok=True)
    for d in os.listdir(SCRATCH_ROOT):          # sweep stale checkouts
        shutil.rmtree(os.path.join(SCRATCH_ROOT, d), ignore_errors=True)

    conn = store.connect(db_path)
    store.init_schema(conn)
    store.migrate(conn)
    reset = store.reset_running_to_queued(conn)
    if reset:
        emit({"type": "log", "level": "info", "msg": f"recovered {reset} interrupted repo(s)"})

    if discover_first and store.ledger_counts(conn)["queued"] < (limit or target):
        emit({"type": "stage", "repo": "", "stage": "discovering"})
        scrape.discover(db_path, target=(limit or target), emit=emit)

    emit({"type": "progress", "processed": 0, **store.ledger_counts(conn)})

    processed = 0
    try:
        while limit is None or processed < limit:
            if _stop["soft"]:
                emit({"type": "log", "level": "info", "msg": "stopping after current queue drain"})
                break
            row = store.claim_next_queued(conn)
            if row is None:
                break
            process_one(conn, row, db_path, emit)
            processed += 1
            emit({"type": "progress", "processed": processed, **store.ledger_counts(conn)})
    except KeyboardInterrupt:
        emit({"type": "log", "level": "warn", "msg": "aborted"})
    conn.close()
    return {"processed": processed}


def _plain(e):
    t = e.get("type")
    if t == "repo_done":
        print(f"[{e.get('status')}] {e.get('repo')}  {e.get('pairs', e.get('reason', ''))}")
    elif t == "stage" and e.get("repo"):
        print(f"  {e['stage']}: {e['repo']}")
    elif t == "log":
        print(f"  ({e.get('level')}) {e.get('msg')}")


def main():
    ap = argparse.ArgumentParser(description="Harvest (asm,source) pairs from many GitHub repos.")
    ap.add_argument("--limit", type=int, default=50, help="max repos to process this run")
    ap.add_argument("--db", default="dataset/pairs.db")
    ap.add_argument("--no-dashboard", action="store_true", help="plain line logging (CI/tests)")
    ap.add_argument("--discover-only", action="store_true", help="only queue repos, don't harvest")
    ap.add_argument("--no-discover", action="store_true", help="drain existing queue only")
    args = ap.parse_args()

    _install_signals()

    if args.discover_only:
        n = scrape.discover(args.db, target=args.limit, emit=lambda e: _plain(e))
        print(f"queued {n} repos")
        return

    def work(emit):
        return harvest(db_path=args.db, limit=args.limit, emit=emit,
                       discover_first=not args.no_discover, target=args.limit)

    if args.no_dashboard:
        work(_plain)
    else:
        try:
            import pipeline.dashboard as dashboard
        except ImportError:
            print("rich not installed; falling back to plain logging "
                  "(pip install rich)", file=sys.stderr)
            work(_plain)
            return
        dashboard.run_with_dashboard(work, limit=args.limit)


if __name__ == "__main__":
    main()
