import json
import os

import pipeline.generate as gen
import pipeline.store as store


def _hybrid_rec(name="h_i32_0", **over):
    rec = {"route": "hybrid", "func_name": name, "lang": "c",
           "signature": f"int {name}(int a, int b)",
           "source_text": f"int {name}(int a, int b) {{\n    return a + b;\n}}\n",
           "seed": 7,
           "asm_text": "   0: add edi, esi\n   2: mov eax, edi\n   4: ret\n",
           "obj_format": "rawx86_64", "compiler": "asmjit", "opt_level": "none"}
    rec.update(over)
    return rec


def _direct_rec(name="d0", **over):
    rec = {"route": "direct", "func_name": name, "lang": "c",
           "signature": f"int {name}(void)",
           "source_text": f"int {name}(void) {{\n    return 0;\n}}\n",
           "seed": 7}
    rec.update(over)
    return rec


def test_parse_records_accepts_valid_and_skips_bad():
    text = "\n".join([
        json.dumps(_hybrid_rec()),
        "{this is not json",                                   # malformed
        json.dumps({"route": "hybrid", "func_name": "x"}),     # missing fields
        json.dumps({"route": "bogus", "func_name": "y"}),      # bad route
        json.dumps({"skip": "h_f64_3", "reason": "err"}),      # stderr noise
        "",                                                    # blank line
        json.dumps(_direct_rec()),
    ])
    recs = gen.parse_records(text)
    assert [r["func_name"] for r in recs] == ["h_i32_0", "d0"]


def test_parse_records_direct_does_not_require_asm():
    recs = gen.parse_records(json.dumps(_direct_rec()))
    assert len(recs) == 1
    assert "asm_text" not in recs[0]


def test_schema_constants_match_frozen_contract():
    assert gen.REQUIRED_COMMON == ("route", "func_name", "lang", "signature",
                                   "source_text", "seed")
    assert gen.REQUIRED_HYBRID == ("asm_text", "obj_format", "compiler",
                                   "opt_level")
    assert gen.JOURNAL_PATH == "dataset/journal-gen.jsonl"
    assert gen.SCRATCH_ROOT.startswith(gen.HOME + os.sep)


def test_ingest_hybrid_origin_values_and_dedup(tmp_path):
    conn = store.connect(str(tmp_path / "g.db"))
    store.init_schema(conn)
    store.migrate(conn)
    stats = gen.ingest_hybrid(conn, [_hybrid_rec(), _hybrid_rec()])  # duplicate
    assert stats == {"pairs": 1, "dedup": 1}
    row = conn.execute(
        "SELECT origin, repo, file_path, arch, opt_level, obj_format, compiler "
        "FROM pairs").fetchone()
    assert row["origin"] == "gen:hybrid"
    assert row["repo"] == "gen:hybrid"
    assert row["file_path"] == "gen/hybrid/h_i32_0.c"
    assert row["arch"] == "x86_64"
    assert row["opt_level"] == "none"
    assert row["obj_format"] == "rawx86_64"
    assert row["compiler"] == "asmjit"


def test_write_direct_repo_one_tu_per_record_under_home(tmp_path):
    scratch = os.path.join(gen.HOME, ".cache", "disasm_generate_test")
    recs = [_direct_rec("d0"), _direct_rec("d1", lang="cpp")]
    try:
        dest = gen.write_direct_repo(recs, scratch_root=scratch)
        assert dest.startswith(gen.HOME + os.sep)   # Colima mount constraint
        with open(os.path.join(dest, "d0.c"), encoding="utf-8") as fh:
            assert fh.read() == recs[0]["source_text"]
        assert os.path.exists(os.path.join(dest, "d1.cpp"))
        # a second batch replaces, not accumulates
        dest2 = gen.write_direct_repo([_direct_rec("d2")], scratch_root=scratch)
        assert not os.path.exists(os.path.join(dest2, "d0.c"))
        assert os.path.exists(os.path.join(dest2, "d2.c"))
    finally:
        import shutil
        shutil.rmtree(scratch, ignore_errors=True)


def test_ingest_direct_threads_origin_and_cleans_up(tmp_path, monkeypatch):
    calls = {}

    def fake_run(repo_dir, repo=None, db_path="dataset/pairs.db",
                 compilers=("gcc", "clang"),
                 opt_levels=("O0", "O1", "O2", "O3", "Os"),
                 progress=None, journal=None, origin="harvest"):
        calls.update(repo_dir=repo_dir, repo=repo, db_path=db_path,
                     origin=origin, existed=os.path.isdir(repo_dir))
        if progress:
            progress({"type": "file", "file": "d0.c", "i": 1, "n": 1})
        return {"pairs": 3, "skipped": 1, "files": 1}

    monkeypatch.setattr(gen.run_pipeline, "run", fake_run)
    monkeypatch.setattr(gen, "SCRATCH_ROOT",
                        os.path.join(gen.HOME, ".cache", "disasm_generate_test"))
    events = []
    stats = gen.ingest_direct([_direct_rec("d0")], str(tmp_path / "g.db"),
                              emit=events.append)
    assert stats == {"pairs": 3, "skipped": 1, "files": 1}
    assert calls["repo"] == "gen:direct"
    assert calls["origin"] == "gen:direct"
    assert calls["repo_dir"].startswith(gen.HOME + os.sep)
    assert calls["existed"] is True                 # repo existed during run
    assert not os.path.exists(calls["repo_dir"])    # ...and is cleaned after
    assert any(e.get("type") == "file" and e.get("repo") == "gen:direct"
               for e in events)


def test_ingest_direct_empty_batch_is_noop(tmp_path):
    stats = gen.ingest_direct([], str(tmp_path / "g.db"))
    assert stats == {"pairs": 0, "skipped": 0, "files": 0}


def test_run_generator_reads_out_file_and_journals(tmp_path, monkeypatch):
    # A fake disasmgen: writes one frozen-schema record to --out, chatter to
    # stderr (which journal.run streams into the mini-box).
    rec_json = json.dumps(_hybrid_rec())
    fake = tmp_path / "disasmgen"
    fake.write_text(
        "#!/bin/sh\n"
        "out=''\n"
        'while [ $# -gt 0 ]; do\n'
        '  if [ "$1" = "--out" ]; then out="$2"; shift; fi\n'
        "  shift\n"
        "done\n"
        'printf %s\\\\n "$REC" > "$out"\n'
        'echo "{\\"done\\":true}" >&2\n')
    fake.chmod(0o755)
    monkeypatch.setenv("REC", rec_json)
    monkeypatch.setattr(gen, "BIN", str(fake))
    monkeypatch.setattr(gen, "SCRATCH_ROOT", str(tmp_path / "scratch"))
    from pipeline.journal import Journal
    j = Journal(path=str(tmp_path / "j.jsonl"))
    try:
        recs = gen.run_generator("hybrid", 1, 7, j)
    finally:
        j.close()
    assert len(recs) == 1
    assert recs[0]["func_name"] == "h_i32_0"
    journal_text = (tmp_path / "j.jsonl").read_text()
    assert "disasmgen" in journal_text          # journal.cmd recorded the argv


def test_run_generator_missing_binary_raises(tmp_path, monkeypatch):
    import pytest
    monkeypatch.setattr(gen, "BIN", str(tmp_path / "nope" / "disasmgen"))
    from pipeline.journal import Journal
    j = Journal(path=str(tmp_path / "j.jsonl"))
    try:
        with pytest.raises(RuntimeError, match="generate.sh"):
            gen.run_generator("hybrid", 1, 0, j)
    finally:
        j.close()


def test_generate_orchestrates_both_routes(tmp_path, monkeypatch):
    monkeypatch.setattr(gen, "JOURNAL_PATH", str(tmp_path / "journal-gen.jsonl"))
    monkeypatch.setattr(
        gen, "run_generator",
        lambda route, count, seed, journal:
        [_hybrid_rec()] if route == "hybrid" else [_direct_rec()])
    monkeypatch.setattr(
        gen, "ingest_direct",
        lambda records, db_path, emit=None, journal=None:
        {"pairs": 2, "skipped": 1, "files": 1})
    events = []
    db = str(tmp_path / "g.db")
    totals = gen.generate(count=1, route="both", db_path=db, seed=7,
                          emit=events.append)
    assert totals == {"pairs": 3, "skipped": 1, "dedup": 0}
    assert os.path.exists(tmp_path / "journal-gen.jsonl")   # own journal file
    assert any(e.get("type") == "repo_done" and e.get("repo") == "gen:hybrid"
               for e in events)
    assert any(e.get("type") == "repo_done" and e.get("repo") == "gen:direct"
               for e in events)
    conn = store.connect(db)
    assert conn.execute(
        "SELECT origin FROM pairs").fetchone()[0] == "gen:hybrid"


def test_generate_single_route_hybrid_only(tmp_path, monkeypatch):
    monkeypatch.setattr(gen, "JOURNAL_PATH", str(tmp_path / "journal-gen.jsonl"))
    seen = []
    monkeypatch.setattr(
        gen, "run_generator",
        lambda route, count, seed, journal: seen.append(route) or [_hybrid_rec()])
    totals = gen.generate(count=1, route="hybrid",
                          db_path=str(tmp_path / "g.db"), seed=0)
    assert seen == ["hybrid"]
    assert totals["pairs"] == 1
