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
