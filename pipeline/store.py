import hashlib
import sqlite3

_SCHEMA = """
CREATE TABLE IF NOT EXISTS pairs (
    id          INTEGER PRIMARY KEY,
    repo        TEXT, file_path TEXT, func_name TEXT, signature TEXT, lang TEXT,
    arch        TEXT, opt_level TEXT, obj_format TEXT, compiler TEXT,
    source_text TEXT, asm_text TEXT,
    source_hash TEXT, asm_hash TEXT,
    pair_hash   TEXT UNIQUE
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
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    conn.commit()


def insert_pair(conn, *, repo, file_path, func_name, signature, lang, arch,
                opt_level, obj_format, compiler, source_text, asm_text) -> bool:
    source_hash = _sha1(source_text)
    asm_hash = _sha1(asm_text)
    pair_hash = _sha1(f"{func_name}\n{asm_text}\n{source_text}")
    cur = conn.execute(
        """INSERT OR IGNORE INTO pairs
           (repo,file_path,func_name,signature,lang,arch,opt_level,obj_format,
            compiler,source_text,asm_text,source_hash,asm_hash,pair_hash)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (repo, file_path, func_name, signature, lang, arch, opt_level, obj_format,
         compiler, source_text, asm_text, source_hash, asm_hash, pair_hash),
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
