from dataclasses import dataclass

from tree_sitter import Language, Parser
import tree_sitter_c
import tree_sitter_cpp

_C = Language(tree_sitter_c.language())
_CPP = Language(tree_sitter_cpp.language())

_C_EXT = {".c"}
_CPP_EXT = {".cc", ".cpp", ".cxx", ".c++", ".C"}
_NAME_TYPES = {"identifier", "field_identifier", "qualified_identifier",
               "destructor_name", "operator_name"}


@dataclass(frozen=True)
class FunctionRecord:
    name: str
    signature: str
    source_text: str
    start_line: int
    is_static: bool
    lang: str


def lang_for(path: str):
    for ext in _C_EXT:
        if path.endswith(ext):
            return "c"
    for ext in _CPP_EXT:
        if path.endswith(ext):
            return "cpp"
    return None


def _descend_declarator(node, target_types):
    """Follow `declarator` fields until reaching a node of a target type."""
    cur = node
    while cur is not None and cur.type not in target_types:
        cur = cur.child_by_field_name("declarator")
    return cur


def _function_name(fn_node, src: bytes):
    decl = _descend_declarator(fn_node.child_by_field_name("declarator"),
                               {"function_declarator"})
    if decl is None:
        return None
    name_node = _descend_declarator(decl.child_by_field_name("declarator"), _NAME_TYPES)
    if name_node is None:
        return None
    text = src[name_node.start_byte:name_node.end_byte].decode("utf-8", "replace")
    return text.split("::")[-1].strip()


def _is_static(fn_node, src: bytes) -> bool:
    for child in fn_node.children:
        if child.type == "storage_class_specifier":
            if src[child.start_byte:child.end_byte] == b"static":
                return True
    return False


def _walk(node):
    stack = [node]
    while stack:
        n = stack.pop()
        if n.type == "function_definition":
            yield n
        stack.extend(n.children)


def extract_functions(path: str):
    lang = lang_for(path)
    if lang is None:
        return []
    with open(path, "rb") as fh:
        src = fh.read()
    parser = Parser(_C if lang == "c" else _CPP)
    tree = parser.parse(src)
    out = []
    for fn in _walk(tree.root_node):
        name = _function_name(fn, src)
        if not name:
            continue
        body = fn.child_by_field_name("body")
        end_sig = body.start_byte if body is not None else fn.end_byte
        signature = src[fn.start_byte:end_sig].decode("utf-8", "replace").strip()
        source_text = src[fn.start_byte:fn.end_byte].decode("utf-8", "replace")
        out.append(FunctionRecord(
            name=name, signature=signature, source_text=source_text,
            start_line=fn.start_point[0] + 1, is_static=_is_static(fn, src), lang=lang,
        ))
    return out
