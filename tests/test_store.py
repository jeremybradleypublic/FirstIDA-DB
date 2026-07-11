import pipeline.store as store


def _mk(tmp_path):
    conn = store.connect(str(tmp_path / "t.db"))
    store.init_schema(conn)
    return conn


def _args(**over):
    base = dict(repo="zlib", file_path="a.c", func_name="foo", signature="int foo(void)",
                lang="c", arch="x86_64", opt_level="O0", obj_format="elf",
                compiler="gcc-12.2.0", source_text="int foo(void){return 1;}",
                asm_text="<foo>:\n ret")
    base.update(over)
    return base


def test_insert_then_dedup(tmp_path):
    conn = _mk(tmp_path)
    assert store.insert_pair(conn, **_args()) is True
    assert store.insert_pair(conn, **_args()) is False   # identical -> dedup
    assert store.count_pairs(conn) == 1


def test_distinct_asm_is_new_row(tmp_path):
    conn = _mk(tmp_path)
    assert store.insert_pair(conn, **_args(asm_text="<foo>:\n nop\n ret")) is True
    assert store.insert_pair(conn, **_args(asm_text="<foo>:\n ret")) is True
    assert store.count_pairs(conn) == 2


def test_record_skip(tmp_path):
    conn = _mk(tmp_path)
    store.record_skip(conn, repo="zlib", file_path="b.c", opt_level="O2", reason="compile failed")
    n = conn.execute("SELECT COUNT(*) FROM skipped").fetchone()[0]
    assert n == 1


import sqlite3
import threading


def test_connect_sets_busy_timeout(tmp_path):
    conn = store.connect(str(tmp_path / "t.db"))
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000


_LEGACY_SCHEMA = """
CREATE TABLE pairs (
    id          INTEGER PRIMARY KEY,
    repo        TEXT, file_path TEXT, func_name TEXT, signature TEXT, lang TEXT,
    arch        TEXT, opt_level TEXT, obj_format TEXT, compiler TEXT,
    source_text TEXT, asm_text TEXT,
    source_hash TEXT, asm_hash TEXT,
    pair_hash   TEXT UNIQUE
);
CREATE TABLE skipped (
    id INTEGER PRIMARY KEY, repo TEXT, file_path TEXT, opt_level TEXT, reason TEXT
);
CREATE TABLE repos (
    id INTEGER PRIMARY KEY, url TEXT, commit_sha TEXT, license TEXT,
    status TEXT, n_pairs INTEGER, processed_at TEXT
);
"""


def test_migrate_concurrent_legacy_no_crash(tmp_path):
    # Two migrators racing on the same pre-origin DB (the harvester + generator
    # upgrade path) must not crash: both see origin missing, both ALTER, and
    # the loser must swallow 'duplicate column name' rather than raise.
    db = str(tmp_path / "legacy.db")
    raw = sqlite3.connect(db)
    raw.executescript(_LEGACY_SCHEMA)
    raw.commit()
    raw.close()

    errs = []
    barrier = threading.Barrier(2)

    def worker():
        conn = store.connect(db)
        try:
            barrier.wait()          # maximise the race window
            store.migrate(conn)
        except Exception as e:      # noqa: BLE001 — record any raise
            errs.append(e)
        finally:
            conn.close()

    t1 = threading.Thread(target=worker)
    t2 = threading.Thread(target=worker)
    t1.start(); t2.start(); t1.join(); t2.join()
    assert errs == [], errs
    conn = store.connect(db)
    assert "origin" in {r[1] for r in conn.execute("PRAGMA table_info(pairs)")}


def test_migrate_adds_origin_and_backfills(tmp_path):
    # Build a pre-origin legacy DB by hand, with one existing harvested row.
    db = str(tmp_path / "legacy.db")
    raw = sqlite3.connect(db)
    raw.executescript(_LEGACY_SCHEMA)
    raw.execute("INSERT INTO pairs (func_name, pair_hash) VALUES ('old_fn', 'h1')")
    raw.commit()
    raw.close()

    conn = store.connect(db)
    store.migrate(conn)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(pairs)")}
    assert "origin" in cols
    row = conn.execute("SELECT origin FROM pairs WHERE func_name='old_fn'").fetchone()
    assert row[0] == "harvest"
    store.migrate(conn)          # idempotent: second run is a no-op
    assert store.count_pairs(conn) == 1


def test_insert_pair_origin_default_and_custom(tmp_path):
    conn = _mk(tmp_path)
    store.migrate(conn)
    assert store.insert_pair(conn, **_args()) is True
    assert conn.execute(
        "SELECT origin FROM pairs WHERE func_name='foo'").fetchone()[0] == "harvest"
    assert store.insert_pair(conn, origin="gen:hybrid",
                             **_args(func_name="hyb")) is True
    assert conn.execute(
        "SELECT origin FROM pairs WHERE func_name='hyb'").fetchone()[0] == "gen:hybrid"


def test_parallel_writers_smoke(tmp_path):
    # Two connections (one per thread, sqlite3 objects are thread-bound)
    # writing the same WAL DB under busy_timeout, without error.
    db = str(tmp_path / "p.db")
    boot = store.connect(db)
    store.init_schema(boot)
    store.migrate(boot)
    boot.close()
    errs = []

    def writer(tag):
        conn = store.connect(db)
        try:
            for i in range(25):
                store.insert_pair(conn, **_args(
                    func_name=f"{tag}_{i}", asm_text=f"<{tag}_{i}>:\n ret"))
        except Exception as e:      # noqa: BLE001 — the test records any failure
            errs.append(e)
        finally:
            conn.close()

    t1 = threading.Thread(target=writer, args=("a",))
    t2 = threading.Thread(target=writer, args=("b",))
    t1.start(); t2.start(); t1.join(); t2.join()
    assert errs == []
    conn = store.connect(db)
    assert store.count_pairs(conn) == 50
