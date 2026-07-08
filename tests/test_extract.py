import os
import pipeline.extract as extract

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def test_lang_for():
    assert extract.lang_for("a.c") == "c"
    assert extract.lang_for("a.cpp") == "cpp"
    assert extract.lang_for("a.cc") == "cpp"
    assert extract.lang_for("a.txt") is None


def test_extract_c_functions():
    recs = extract.extract_functions(os.path.join(FIX, "simple.c"))
    by_name = {r.name: r for r in recs}
    assert set(by_name) == {"helper", "addtwo"}
    assert by_name["helper"].is_static is True
    assert by_name["addtwo"].is_static is False
    assert by_name["addtwo"].lang == "c"
    assert "return x + y;" in by_name["addtwo"].source_text
    assert by_name["addtwo"].signature.startswith("int addtwo(int x, int y)")


def test_extract_cpp_overloads():
    recs = extract.extract_functions(os.path.join(FIX, "overload.cpp"))
    assert [r.name for r in recs] == ["add", "add"]
    assert all(r.lang == "cpp" for r in recs)
