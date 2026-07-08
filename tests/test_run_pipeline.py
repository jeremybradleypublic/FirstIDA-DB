import os
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
