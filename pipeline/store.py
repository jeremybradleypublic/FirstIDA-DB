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
    origin      TEXT,
    session     TEXT
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
                origin='harvest', session=None) -> bool:
    source_hash = _sha1(source_text)
    asm_hash = _sha1(asm_text)
    pair_hash = _sha1(f"{func_name}\n{asm_text}\n{source_text}")
    cur = conn.execute(
        """INSERT OR IGNORE INTO pairs
           (repo,file_path,func_name,signature,lang,arch,opt_level,obj_format,
            compiler,source_text,asm_text,source_hash,asm_hash,pair_hash,origin,session)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (repo, file_path, func_name, signature, lang, arch, opt_level, obj_format,
         compiler, source_text, asm_text, source_hash, asm_hash, pair_hash, origin, session),
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

def _add_column_if_missing(conn, table, col, decl) -> None:
    """Add a column, tolerating a concurrent migrator that added it first.
    The table_info check avoids the ALTER in the common case; the try/except
    covers the cross-process race where two processes both see it missing and
    both ALTER — busy_timeout only retries on locks, not on the logical
    'duplicate column name' error the loser would otherwise raise uncaught."""
    cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    if col in cols:
        return
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
    except sqlite3.OperationalError as e:
        if "duplicate column name" not in str(e).lower():
            raise


def migrate(conn) -> None:
    """Idempotent PRAGMA-guarded migrations: repos harvest columns, and the
    pairs.origin provenance column (existing rows backfilled to 'harvest').
    Safe to run concurrently from the harvester and the generator."""
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_repos_url ON repos(url)")
    _add_column_if_missing(conn, "repos", "reason", "TEXT")
    _add_column_if_missing(conn, "repos", "stars", "INTEGER")
    _add_column_if_missing(conn, "pairs", "origin", "TEXT")
    _add_column_if_missing(conn, "pairs", "session", "TEXT")
    conn.execute("UPDATE pairs SET origin='harvest' WHERE origin IS NULL")
    # Self-documenting view: anyone opening pairs.db sees a coarse source_system
    # column that names WHERE each pair came from — the git scraper vs. the
    # synthetic generator — without having to know the origin encoding.
    conn.execute("""CREATE VIEW IF NOT EXISTS pairs_labeled AS
        SELECT *, CASE
            WHEN origin = 'harvest'   THEN 'git-scraper'
            WHEN origin LIKE 'gen:%'  THEN 'generator'
            ELSE COALESCE(origin, 'unknown') END AS source_system
        FROM pairs""")
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


def all_repos(conn):
    """Every repo the scraper has touched, most-productive first."""
    return conn.execute(
        "SELECT url, status, stars, license, commit_sha, n_pairs, processed_at "
        "FROM repos ORDER BY (n_pairs IS NULL), n_pairs DESC, id").fetchall()


def export_sources(conn, path):
    """Write the list of git repos the scraper used to a TSV file (for storage/
    provenance). Returns (path, count)."""
    import os
    rows = all_repos(conn)
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    cols = ("url", "status", "stars", "license", "commit_sha", "n_pairs", "processed_at")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\t".join(cols) + "\n")
        for r in rows:
            fh.write("\t".join("" if r[c] is None else str(r[c]) for c in cols) + "\n")
    return path, len(rows)
