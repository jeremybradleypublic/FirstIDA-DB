import re
from dataclasses import dataclass

_HEADER = re.compile(r"^[0-9a-fA-F]+ <(?P<name>.+)>:$")


@dataclass(frozen=True)
class AsmFunc:
    symbol: str
    demangled: str
    asm_text: str


def parse_objdump(text: str):
    funcs = []
    cur_name = None
    cur_lines = []

    def flush():
        if cur_name is not None:
            asm = "\n".join(cur_lines).rstrip()
            funcs.append(AsmFunc(symbol=cur_name, demangled=cur_name, asm_text=asm))

    for raw in text.splitlines():
        m = _HEADER.match(raw.strip())
        if m:
            flush()
            cur_name = m.group("name")
            cur_lines = [f"<{cur_name}>:"]
        elif cur_name is not None:
            if raw.strip() == "":
                continue
            cur_lines.append(raw.rstrip())
    flush()
    return funcs


def _demangle(tc, names):
    """Batch-demangle symbol names with c++filt; returns {name: demangled}."""
    if not names:
        return {}
    ordered = list(names)
    out = tc.exec(["c++filt"], input="\n".join(ordered) + "\n")
    demangled = out.stdout.splitlines()
    result = {}
    for i, n in enumerate(ordered):
        result[n] = demangled[i] if i < len(demangled) else n
    return result


def disassemble(tc, obj_container_path: str):
    raw = tc.exec(["objdump", "-d", obj_container_path])
    parsed = parse_objdump(raw.stdout)
    dm = _demangle(tc, [f.symbol for f in parsed])
    return [AsmFunc(symbol=f.symbol, demangled=dm.get(f.symbol, f.symbol),
                    asm_text=f.asm_text) for f in parsed]
