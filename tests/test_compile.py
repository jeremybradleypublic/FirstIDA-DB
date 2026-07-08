import pytest
import pipeline.compile as compile_mod
import pipeline.disasm as disasm

pytestmark = pytest.mark.integration


def test_compile_and_disassemble_minirepo(toolchain):
    res = compile_mod.compile_tu(toolchain, "add.c", "gcc", "O0", "c", ["/src"])
    assert res.ok, res.reason
    funcs = disasm.disassemble(toolchain, res.obj_path)
    names = {f.symbol for f in funcs}
    # 'add' and 'use' are external; 'mul' is static (may survive at O0)
    assert "add" in names and "use" in names


def test_compile_failure_is_reported(toolchain):
    # rel_src does not exist in /src -> compiler error, not an exception
    res = compile_mod.compile_tu(toolchain, "nope.c", "gcc", "O2", "c", ["/src"])
    assert res.ok is False and res.reason
