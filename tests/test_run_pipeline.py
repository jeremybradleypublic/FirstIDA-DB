import os
import shutil
import tempfile

import pytest
import pipeline.run_pipeline as rp
import pipeline.store as store

pytestmark = pytest.mark.integration
FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def test_run_on_minirepo_populates_db(tmp_path):
    import pipeline.env as env
    if not env.docker_available():
        pytest.skip("Docker/Colima not available")
    db = str(tmp_path / "pairs.db")
    stats = rp.run(os.path.join(FIX, "minirepo"), repo="minirepo", db_path=db,
                   compilers=("gcc",), opt_levels=("O0",))
    assert stats["pairs"] >= 1
    conn = store.connect(db)
    names = {row[0] for row in conn.execute("SELECT func_name FROM pairs")}
    assert "add" in names
    # idempotent: a second identical run adds no new rows
    before = store.count_pairs(conn)
    rp.run(os.path.join(FIX, "minirepo"), repo="minirepo", db_path=db,
           compilers=("gcc",), opt_levels=("O0",))
    assert store.count_pairs(store.connect(db)) == before


def test_run_skips_uncompilable_file_and_continues(tmp_path):
    import pipeline.env as env
    if not env.docker_available():
        pytest.skip("Docker/Colima not available")
    # The dockerized toolchain container is bind-mounted from the host, but
    # Colima (by default) only virtiofs-mounts the user's home directory tree
    # into its VM, not the OS temp dir that pytest's `tmp_path` lives under.
    # Build the source repo in a project-local temp dir (still under $HOME)
    # so it is actually visible inside the container; keep using `tmp_path`
    # for the sqlite db path, which the toolchain never needs to see.
    repo_dir = tempfile.mkdtemp(dir=os.path.dirname(__file__))
    try:
        with open(os.path.join(repo_dir, "good.c"), "w") as fh:
            fh.write("int good(int x){return x+1;}\n")
        with open(os.path.join(repo_dir, "bad.c"), "w") as fh:
            fh.write("int bad(void) { this is not valid c }\n")
        db = str(tmp_path / "m.db")
        stats = rp.run(repo_dir, repo="mixed", db_path=db,
                       compilers=("gcc",), opt_levels=("O0",))
        assert stats["skipped"] >= 1
        assert stats["pairs"] >= 1
        conn = store.connect(db)
        names = {row[0] for row in conn.execute("SELECT func_name FROM pairs")}
        assert "good" in names
    finally:
        shutil.rmtree(repo_dir, ignore_errors=True)
