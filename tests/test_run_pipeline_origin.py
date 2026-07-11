"""Hermetic (no Docker) proof that run_pipeline.run threads `origin` into
store.insert_pair. All container-facing seams are monkeypatched."""
import types

import pipeline.run_pipeline as rp


class _FakeTC:
    def stop(self):
        pass


def _stub_pipeline(monkeypatch, calls):
    monkeypatch.setattr(rp.env, "start_toolchain",
                        lambda repo_dir, journal=None: _FakeTC())
    monkeypatch.setattr(rp.extract, "extract_functions", lambda path: ["rec"])
    monkeypatch.setattr(rp.compile_mod, "compiler_label",
                        lambda tc, compiler, lang: f"{compiler}-0.0-fake")
    monkeypatch.setattr(
        rp.compile_mod, "compile_tu",
        lambda tc, rel, compiler, opt, lang, incs:
        types.SimpleNamespace(ok=True, obj_path="/out/a.o", reason=None))
    monkeypatch.setattr(rp.disasm, "disassemble", lambda tc, obj: ["asm-stub"])
    monkeypatch.setattr(
        rp.pair, "pair_functions",
        lambda records, asm: [types.SimpleNamespace(
            func_name="f", signature="int f(void)", lang="c",
            source_text="int f(void){return 0;}", asm_text="<f>:\n ret")])

    def fake_insert(conn, **kw):
        calls.append(kw)
        return True
    monkeypatch.setattr(rp.store, "insert_pair", fake_insert)


def _mk_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.c").write_text("int f(void){return 0;}\n")
    return str(repo)


def test_default_origin_is_harvest(tmp_path, monkeypatch):
    calls = []
    _stub_pipeline(monkeypatch, calls)
    rp.run(_mk_repo(tmp_path), repo="stub", db_path=str(tmp_path / "d.db"),
           compilers=("gcc",), opt_levels=("O0",))
    assert calls
    assert all(c["origin"] == "harvest" for c in calls)


def test_origin_param_is_threaded(tmp_path, monkeypatch):
    calls = []
    _stub_pipeline(monkeypatch, calls)
    stats = rp.run(_mk_repo(tmp_path), repo="stub", db_path=str(tmp_path / "d.db"),
                   compilers=("gcc",), opt_levels=("O0",), origin="gen:direct")
    assert stats["pairs"] == 1
    assert calls
    assert all(c["origin"] == "gen:direct" for c in calls)


def test_run_migrates_legacy_db(tmp_path, monkeypatch):
    """run() must be self-sufficient: on a pre-origin legacy pairs.db it adds
    the column itself (real callers migrate, but standalone run() must too)."""
    import sqlite3
    db = str(tmp_path / "legacy.db")
    raw = sqlite3.connect(db)
    raw.executescript(
        "CREATE TABLE pairs (id INTEGER PRIMARY KEY, func_name TEXT, "
        "asm_text TEXT, source_text TEXT, pair_hash TEXT UNIQUE);"
        "CREATE TABLE skipped (id INTEGER PRIMARY KEY, repo TEXT, "
        "file_path TEXT, opt_level TEXT, reason TEXT);"
        "CREATE TABLE repos (id INTEGER PRIMARY KEY, url TEXT, status TEXT);")
    raw.close()
    calls = []
    _stub_pipeline(monkeypatch, calls)
    rp.run(_mk_repo(tmp_path), repo="stub", db_path=db,
           compilers=("gcc",), opt_levels=("O0",), origin="gen:direct")
    conn = rp.store.connect(db)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(pairs)")}
    assert "origin" in cols   # run() migrated the legacy DB on its own
