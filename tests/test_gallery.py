import pipeline.store as store
import pipeline.gallery as gallery
import pipeline.generate as gen
from pipeline.journal import Journal


def _ins(conn, **over):
    args = dict(repo="gen:hybrid", file_path="g/f.c", func_name="f",
                signature="int f(int a, int b)", lang="c", arch="x86_64",
                opt_level="none", obj_format="rawx86_64", compiler="asmjit",
                source_text="int f(int a, int b){return a+b;}",
                asm_text="0: add edi, esi", origin="gen:hybrid")
    args.update(over)
    return store.insert_pair(conn, **args)


def _seed(db):
    conn = store.connect(db)
    store.init_schema(conn)
    store.migrate(conn)
    _ins(conn, func_name="h_a", origin="gen:hybrid", session="gen-S1")
    _ins(conn, func_name="d_x", origin="gen:direct", obj_format="elf",
         compiler="gcc-12.2.0", opt_level="O0", asm_text="<d_x>:\n ret", session="gen-S1")
    _ins(conn, func_name="harv_fn", origin="harvest", obj_format="elf",
         compiler="gcc-12.2.0", opt_level="O2", asm_text="<harv_fn>:\n ret")
    conn.commit()
    conn.close()


def test_gallery_includes_both_sources(tmp_path):
    db = str(tmp_path / "g.db")
    _seed(db)
    text = open(gallery.build_gallery(db, str(tmp_path / "g.html")),
                encoding="utf-8").read()
    # the git scraper is now connected to the page too
    assert "h_a" in text and "d_x" in text and "harv_fn" in text
    assert "git-scraper" in text and "generator" in text
    assert "FirstIDA-DB console" in text          # the advanced console shell
    assert 'id=p-journal' in text and 'id=p-sources' in text and 'id=p-graph' in text


def test_gallery_embeds_sessions_and_sources(tmp_path):
    db = str(tmp_path / "g.db")
    _seed(db)
    conn = store.connect(db)
    store.migrate(conn)
    store.ensure_repo_queued(conn, "https://github.com/a/b", "mit", 42)
    rid = conn.execute("SELECT id FROM repos WHERE url LIKE '%a/b'").fetchone()[0]
    store.mark_repo(conn, rid, "done", n_pairs=17, commit_sha="abc")
    conn.commit()
    conn.close()
    text = open(gallery.build_gallery(db, str(tmp_path / "g.html")),
                encoding="utf-8").read()
    assert "gen-S1" in text                        # session id embedded
    assert "https://github.com/a/b" in text        # scraper's repo list embedded


def test_gallery_hybrid_gets_symbol_header(tmp_path):
    db = str(tmp_path / "g.db")
    conn = store.connect(db)
    store.init_schema(conn)
    store.migrate(conn)
    # a legacy hybrid row whose asm has no <symbol>: header
    _ins(conn, func_name="h_acc_i_1", origin="gen:hybrid", asm_text="0: mov eax, 1")
    conn.commit()
    conn.close()
    text = open(gallery.build_gallery(db, str(tmp_path / "g.html")),
                encoding="utf-8").read()
    assert "<h_acc_i_1>:" in text                  # header synthesized for display


def test_gallery_neutralises_script_break(tmp_path):
    db = str(tmp_path / "g.db")
    conn = store.connect(db)
    store.init_schema(conn)
    store.migrate(conn)
    _ins(conn, func_name="evil", origin="gen:hybrid",
         source_text="x</script>y", asm_text="0: ret")
    conn.commit()
    conn.close()
    text = open(gallery.build_gallery(db, str(tmp_path / "g.html")),
                encoding="utf-8").read()
    assert "x</script>y" not in text               # not left raw in the <script>
    assert "x<\\/script>y" in text                 # neutralised to <\/script>


def test_gallery_empty_db_is_valid(tmp_path):
    db = str(tmp_path / "empty.db")
    conn = store.connect(db)
    store.init_schema(conn)
    store.migrate(conn)
    conn.close()
    text = open(gallery.build_gallery(db, str(tmp_path / "e.html")),
                encoding="utf-8").read()
    assert "FirstIDA-DB console" in text
    assert '"pairs": []' in text or '"pairs":[]' in text


def test_asm_with_header_helper():
    assert gen._asm_with_header({"func_name": "h0", "asm_text": "0: ret"}) == "<h0>:\n0: ret"
    # already-headered asm is left alone
    assert gen._asm_with_header({"func_name": "h0", "asm_text": "<h0>:\n0: ret"}) \
        == "<h0>:\n0: ret"


def test_ingest_hybrid_streams_each_function(tmp_path):
    db = str(tmp_path / "g.db")
    conn = store.connect(db)
    store.init_schema(conn)
    store.migrate(conn)
    jp = str(tmp_path / "j.jsonl")
    j = Journal(path=jp)
    recs = [{"route": "hybrid", "func_name": "h_stream_0", "lang": "c",
             "signature": "int h_stream_0(int a, int b)",
             "source_text": "int h_stream_0(int a, int b){return a;}", "seed": 1,
             "asm_text": "0: ret", "obj_format": "rawx86_64",
             "compiler": "asmjit", "opt_level": "none"}]
    gen.ingest_hybrid(conn, recs, journal=j, session="gen-T")
    j.close()
    conn.close()
    assert "h_stream_0" in open(jp, encoding="utf-8").read()
