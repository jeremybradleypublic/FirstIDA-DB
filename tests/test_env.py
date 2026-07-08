import pytest
import pipeline.env as env

pytestmark = pytest.mark.integration


def test_container_runs_gcc_and_objdump(toolchain):
    r = toolchain.exec(["gcc", "--version"])
    assert r.returncode == 0 and "gcc" in r.stdout.lower()
    r = toolchain.exec(["clang", "--version"])
    assert r.returncode == 0 and "clang" in r.stdout.lower()
    r = toolchain.exec(["objdump", "--version"])
    assert r.returncode == 0
    # /src is mounted read-only and contains the mini repo
    r = toolchain.exec(["ls", "/src"])
    assert "add.c" in r.stdout
