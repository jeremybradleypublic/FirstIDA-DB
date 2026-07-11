import hashlib
import sqlite3
from datetime import datetime, timezone

_SCHEMA = """
CREATE TABLE IF NOT EXISTS pairs (
    id          INTEGER PRIMARY KEY,
    repo        TEXT, file_path TEXT, func_name TEXT, signature TEXT, lang TEXT,
    arch        TEXT, opt_level TEXT, obj_format TEXT, compiler TEXT,
    source_text TEXT, asm_text TEXT,
    source_hash TEXT, asm_hash TEXT,
    pair_hash   TEXT UNIQUE,
    origin      TEXT
);
CREATE TABLE IF NOT EXISTS skipped (
    id INTEGER PRIMARY KEY, repo TEXT, file_path TEXT, opt_level TEXT, reason TEXT
);
CREATE TABLE IF NOT EXISTS repos (
    id INTEGER PRIMARY KEY, url TEXT, commit_sha TEXT, license TEXT,
    status TEXT, n_pairs INTEGER, processed_at TEXT
);
"""


def _sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8", "surrogatepass")).hexdigest()


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    # The harvester and the generator write the same DB in parallel; WAL
    # allows one writer at a time, and busy_timeout retries instead of
    # raising an immediate "database is locked".
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    conn.commit()


def insert_pair(conn, *, repo, file_path, func_name, signature, lang, arch,
                opt_level, obj_format, compiler, source_text, asm_text,
                origin='harvest') -> bool:
    source_hash = _sha1(source_text)
    asm_hash = _sha1(asm_text)
    pair_hash = _sha1(f"{func_name}\n{asm_text}\n{source_text}")
    cur = conn.execute(
        """INSERT OR IGNORE INTO pairs
           (repo,file_path,func_name,signature,lang,arch,opt_level,obj_format,
            compiler,source_text,asm_text,source_hash,asm_hash,pair_hash,origin)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (repo, file_path, func_name, signature, lang, arch, opt_level, obj_format,
         compiler, source_text, asm_text, source_hash, asm_hash, pair_hash, origin),
    )
    conn.commit()
    return cur.rowcount == 1


def record_skip(conn, *, repo, file_path, opt_level, reason) -> None:
    conn.execute(
        "INSERT INTO skipped (repo,file_path,opt_level,reason) VALUES (?,?,?,?)",
        (repo, file_path, opt_level, reason),
    )
    conn.commit()


def count_pairs(conn) -> int:
    return conn.execute("SELECT COUNT(*) FROM pairs").fetchone()[0]


# --- repos ledger (Phase-2 harvest) ---------------------------------------

def migrate(conn) -> None:
    """Idempotent PRAGMA-guarded migrations: repos harvest columns, and the
    pairs.origin provenance column (existing rows backfilled to 'harvest')."""
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_repos_url ON repos(url)")
    cols = {r[1] for r in conn.execute("PRAGMA table_info(repos)")}
    if "reason" not in cols:
        conn.execute("ALTER TABLE repos ADD COLUMN reason TEXT")
    if "stars" not in cols:
        conn.execute("ALTER TABLE repos ADD COLUMN stars INTEGER")
    pair_cols = {r[1] for r in conn.execute("PRAGMA table_info(pairs)")}
    if "origin" not in pair_cols:
        conn.execute("ALTER TABLE pairs ADD COLUMN origin TEXT")
    conn.execute("UPDATE pairs SET origin='harvest' WHERE origin IS NULL")
    conn.commit()


def ensure_repo_queued(conn, url, license, stars) -> bool:
    """Queue a repo for harvesting. Returns True if newly inserted."""
    cur = conn.execute(
        "INSERT OR IGNORE INTO repos (url, license, stars, status) VALUES (?,?,?,'queued')",
        (url, license, stars),
    )
    conn.commit()
    return cur.rowcount == 1


def reset_running_to_queued(conn) -> int:
    """Recover repos left 'running' by a previous crash. Returns count reset."""
    cur = conn.execute("UPDATE repos SET status='queued' WHERE status='running'")
    conn.commit()
    return cur.rowcount


def claim_next_queued(conn):
    """Atomically take the next queued repo (highest stars first) and mark it running."""
    row = conn.execute(
        "SELECT * FROM repos WHERE status='queued' "
        "ORDER BY (stars IS NULL), stars DESC, id LIMIT 1"
    ).fetchone()
    if row is not None:
        conn.execute("UPDATE repos SET status='running' WHERE id=?", (row["id"],))
        conn.commit()
    return row


def mark_repo(conn, repo_id, status, *, n_pairs=None, commit_sha=None, reason=None) -> None:
    conn.execute(
        """UPDATE repos SET status=?,
               n_pairs=COALESCE(?, n_pairs),
               commit_sha=COALESCE(?, commit_sha),
               reason=COALESCE(?, reason),
               processed_at=? WHERE id=?""",
        (status, n_pairs, commit_sha, reason,
         datetime.now(timezone.utc).isoformat(timespec="seconds"), repo_id),
    )
    conn.commit()


def ledger_counts(conn) -> dict:
    d = {r[0]: r[1] for r in conn.execute("SELECT status, COUNT(*) FROM repos GROUP BY status")}
    return {"queued": d.get("queued", 0), "running": d.get("running", 0),
            "done": d.get("done", 0), "failed": d.get("failed", 0)}
