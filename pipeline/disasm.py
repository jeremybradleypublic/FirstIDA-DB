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
