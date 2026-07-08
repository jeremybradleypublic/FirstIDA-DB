from pipeline.extract import FunctionRecord
from pipeline.disasm import AsmFunc
import pipeline.pair as pair


def _rec(name, lang="c"):
    return FunctionRecord(name=name, signature=f"int {name}(void)",
                          source_text=f"int {name}(void){{return 0;}}",
                          start_line=1, is_static=False, lang=lang)


def test_base_name_strips_gcc_clone_suffix():
    assert pair.base_name("deflate.constprop.0", "deflate.constprop.0") == "deflate"
    assert pair.base_name("fill.part.3", "fill.part.3") == "fill"


def test_base_name_cpp_from_demangled():
    assert pair.base_name("_Z3addii", "add(int, int)") == "add"


def test_pair_matches_by_name_and_drops_unmatched():
    recs = [_rec("addtwo"), _rec("inlined_away")]
    asm = [AsmFunc(symbol="addtwo", demangled="addtwo", asm_text="<addtwo>:\n ret")]
    pairs = pair.pair_functions(recs, asm)
    assert len(pairs) == 1
    assert pairs[0].func_name == "addtwo"
    assert pairs[0].asm_text == "<addtwo>:\n ret"


def test_pair_matches_gcc_clone_to_source():
    recs = [_rec("deflate")]
    asm = [AsmFunc(symbol="deflate.constprop.0", demangled="deflate.constprop.0",
                   asm_text="<deflate.constprop.0>:\n ret")]
    pairs = pair.pair_functions(recs, asm)
    assert len(pairs) == 1 and pairs[0].func_name == "deflate"
