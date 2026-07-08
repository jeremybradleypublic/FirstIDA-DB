import os
import pipeline.disasm as disasm

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def test_parse_objdump_splits_symbols():
    text = open(os.path.join(FIX, "objdump_sample.txt")).read()
    funcs = disasm.parse_objdump(text)
    by_sym = {f.symbol: f for f in funcs}
    assert set(by_sym) == {"addtwo", "_Z3addii"}
    assert by_sym["addtwo"].asm_text.startswith("<addtwo>:")
    assert "ret" in by_sym["addtwo"].asm_text
    # the second function's instructions do not leak into the first
    assert "_Z3addii" not in by_sym["addtwo"].asm_text
