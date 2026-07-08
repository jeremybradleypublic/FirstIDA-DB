import re
from dataclasses import dataclass

from pipeline.extract import FunctionRecord
from pipeline.disasm import AsmFunc

_CLONE = re.compile(r"\.(constprop|isra|part|cold|lto_priv|clone)(\.\d+)*$")


@dataclass(frozen=True)
class Pair:
    func_name: str
    signature: str
    source_text: str
    asm_text: str
    lang: str


def base_name(symbol: str, demangled: str) -> str:
    if "(" in demangled:                       # C++ demangled signature
        head = demangled.split("(", 1)[0]
        return head.split("::")[-1].strip()
    s = _CLONE.sub("", symbol)
    return s.lstrip("_")


def pair_functions(records, asm):
    index = {}
    for a in asm:
        key = base_name(a.symbol, a.demangled)
        index.setdefault(key, a)             # first symbol wins on collision
    out = []
    for r in records:
        a = index.get(r.name)
        if a is None:
            continue
        out.append(Pair(func_name=r.name, signature=r.signature,
                        source_text=r.source_text, asm_text=a.asm_text, lang=r.lang))
    return out
