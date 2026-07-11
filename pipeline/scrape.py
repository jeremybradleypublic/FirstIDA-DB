"""Discover permissively-licensed C/C++ repos on GitHub and queue them in the
`repos` ledger. Shells out to the already-authenticated `gh` CLI (no token in code)."""
import json
import subprocess
import time
from collections import Counter

import pipeline.store as store

# gh --language values
_LANG_GH = {"c": "C", "cpp": "C++"}
LANGS = ("c", "cpp")
TOPICS = ("compression", "cryptography", "parser", "database", "networking",
          "embedded", "graphics", "image-processing", "math", "kernel", "cli")
# Star buckets keep each query under GitHub's 1000-results-per-search cap.
BUCKETS = ("10..50", "50..200", "200..1000", ">1000")

PERMISSIVE = {"mit", "apache-2.0", "bsd-2-clause", "bsd-3-clause", "zlib",
              "isc", "0bsd", "unlicense"}
# Heavily-vendored libs — skip to limit duplicate functions across repos.
_BLOCK = ("zlib", "sqlite", "stb", "miniz", "lz4", "zstd", "libpng", "zziplib")

PER_OWNER_CAP = 3
_SIZE_MIN_KB = 50
_SIZE_MAX_KB = 300_000
_SEARCH_PACE_S = 2.1          # search API is ~30/min; stay under it


def _gh_search(lang, topic, bucket, limit=60, journal=None):
    cmd = ["gh", "search", "repos",
           "fork:false pushed:>2021-01-01",
           "--language", _LANG_GH[lang],
           "--topic", topic,
           "--stars", bucket,
           "--archived=false",
           "--limit", str(limit),
           "--json", "fullName,url,stargazersCount,license,owner,isFork,size"]
    if journal:
        journal.cmd(cmd)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return None, "timeout"
    if r.returncode != 0:
        return None, (r.stderr or "").strip()[:120]
    try:
        return json.loads(r.stdout or "[]"), None
    except json.JSONDecodeError as e:
        return None, str(e)


def _keep(item):
    lic = (item.get("license") or {}).get("key")
    if lic not in PERMISSIVE:
        return None
    if item.get("isFork"):
        return None
    full = item.get("fullName") or ""
    name = full.split("/")[-1].lower()
    if any(b in name for b in _BLOCK):
        return None
    size = item.get("size") or 0
    if size < _SIZE_MIN_KB or size > _SIZE_MAX_KB:
        return None
    url = item.get("url")
    if not url:
        return None
    return {"url": url, "full": full,
            "owner": (item.get("owner") or {}).get("login", ""),
            "stars": item.get("stargazersCount", 0), "license": lic}


def discover(db_path, target=50, emit=lambda e: None, journal=None):
    """Search slices until ~target*4 candidates gathered, then queue up to target*2
    (highest-starred first, capped per owner). Returns count newly queued."""
    conn = store.connect(db_path)
    store.init_schema(conn)
    store.migrate(conn)

    if journal:
        journal.event(f"discovery: searching GitHub for up to {target} repos")
    candidates = {}
    slices = [(l, t, b) for l in LANGS for t in TOPICS for b in BUCKETS]
    for lang, topic, bucket in slices:
        data, err = _gh_search(lang, topic, bucket, journal=journal)
        found = len(data) if data else 0
        emit({"type": "discover", "slice": f"{lang}/{topic}/{bucket}", "found": found})
        if err:
            emit({"type": "log", "level": "warn", "msg": f"gh {lang}/{topic}/{bucket}: {err}"})
            if journal:
                journal.event(f"gh {lang}/{topic}/{bucket}: {err}", level="warn")
            if "rate limit" in err.lower() or "secondary" in err.lower():
                emit({"type": "log", "level": "warn", "msg": "search rate limit; backing off 30s"})
                if journal:
                    journal.event("search rate limit; backing off 30s", level="warn")
                time.sleep(30)
            else:
                time.sleep(_SEARCH_PACE_S)
            continue
        if journal:
            journal.event(f"slice {lang}/{topic}/{bucket} → {found} repos")
        if found == 1000:
            emit({"type": "log", "level": "warn",
                  "msg": f"slice {lang}/{topic}/{bucket} saturated (1000)"})
        for item in data or []:
            kept = _keep(item)
            if kept:
                candidates.setdefault(kept["url"], kept)
        if len(candidates) >= target * 4:
            break
        time.sleep(_SEARCH_PACE_S)

    per_owner = Counter()
    queued = 0
    for c in sorted(candidates.values(), key=lambda x: -x["stars"]):
        if per_owner[c["owner"]] >= PER_OWNER_CAP:
            continue
        per_owner[c["owner"]] += 1
        if store.ensure_repo_queued(conn, c["url"], c["license"], c["stars"]):
            queued += 1
        if queued >= target * 2:
            break
    conn.close()
    emit({"type": "log", "level": "info",
          "msg": f"discovery: {len(candidates)} candidates, {queued} newly queued"})
    if journal:
        journal.event(f"discovery finished: {len(candidates)} candidates, "
                      f"{queued} newly queued")
    return queued


def discover_from_file(db_path, path, emit=lambda e: None):
    """Queue repos from a plain text file of URLs (one per line)."""
    conn = store.connect(db_path)
    store.init_schema(conn)
    store.migrate(conn)
    queued = 0
    with open(path) as fh:
        for line in fh:
            url = line.strip()
            if url and not url.startswith("#"):
                if store.ensure_repo_queued(conn, url, None, None):
                    queued += 1
    conn.close()
    return queued
