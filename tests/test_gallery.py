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
    _ins(conn, func_name="h_a", origin="gen:hybrid")
    _ins(conn, func_name="d_x", origin="gen:direct", obj_format="elf",
         compiler="gcc-12.2.0", opt_level="O0")
    _ins(conn, func_name="harv_fn", origin="harvest", obj_format="elf",
         compiler="gcc-12.2.0", opt_level="O2")   # must be excluded by default
    conn.commit()
    conn.close()


def test_gallery_generated_only_by_default(tmp_path):
    db = str(tmp_path / "g.db")
    _seed(db)
    text = open(gallery.build_gallery(db, str(tmp_path / "g.html")),
                encoding="utf-8").read()
    assert "h_a" in text and "d_x" in text
    assert "harv_fn" not in text          # harvested rows excluded from gen:%
    assert "asmjit" in text and "gcc-12.2.0" in text
    assert 'data-f="direct"' in text and 'data-f="hybrid"' in text  # filter chips


def test_gallery_escapes_html(tmp_path):
    db = str(tmp_path / "g.db")
    conn = store.connect(db)
    store.init_schema(conn)
    store.migrate(conn)
    _ins(conn, func_name="cmp_lt", origin="gen:direct",
         source_text="int cmp_lt(int a, int b){return a < b && a > 0;}",
         asm_text="0: cmp edi, esi  <tag>")
    conn.commit()
    conn.close()
    text = open(gallery.build_gallery(db, str(tmp_path / "x.html")),
                encoding="utf-8").read()
    assert "a &lt; b &amp;&amp; a &gt; 0" in text   # escaped source
    assert "&lt;tag&gt;" in text                    # escaped asm
    assert "a < b &&" not in text                   # never raw


def test_gallery_all_includes_harvest(tmp_path):
    db = str(tmp_path / "g.db")
    _seed(db)
    text = open(gallery.build_gallery(db, str(tmp_path / "all.html"),
                                      origin_like="%"), encoding="utf-8").read()
    assert "harv_fn" in text


def test_gallery_empty_db_is_valid(tmp_path):
    db = str(tmp_path / "empty.db")
    conn = store.connect(db)
    store.init_schema(conn)
    store.migrate(conn)
    conn.close()
    text = open(gallery.build_gallery(db, str(tmp_path / "e.html")),
                encoding="utf-8").read()
    assert "No generated pairs yet" in text


def test_ingest_hybrid_streams_each_function(tmp_path):
    # live visibility: each generated function is written to the journal
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
    gen.ingest_hybrid(conn, recs, journal=j)
    j.close()
    conn.close()
    assert "h_stream_0" in open(jp, encoding="utf-8").read()
