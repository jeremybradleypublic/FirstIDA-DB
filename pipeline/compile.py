import hashlib
import re
from dataclasses import dataclass

_BIN = {("gcc", "c"): "gcc", ("gcc", "cpp"): "g++",
        ("clang", "c"): "clang", ("clang", "cpp"): "clang++"}
_VER = re.compile(r"(\d+\.\d+\.\d+)")


@dataclass(frozen=True)
class CompileResult:
    ok: bool
    obj_path: str | None
    reason: str | None


def compiler_binary(compiler: str, lang: str) -> str:
    return _BIN[(compiler, lang)]


def compiler_label(tc, compiler: str, lang: str) -> str:
    out = tc.exec([compiler_binary(compiler, lang), "--version"]).stdout
    m = _VER.search(out)
    return f"{compiler}-{m.group(1)}" if m else compiler


def compile_tu(tc, rel_src: str, compiler: str, opt: str, lang: str, include_dirs) -> CompileResult:
    cc = compiler_binary(compiler, lang)
    obj = hashlib.sha1(f"{rel_src}:{compiler}:{opt}".encode()).hexdigest()[:16] + ".o"
    obj_path = f"/out/{obj}"
    argv = [cc, f"-{opt}", "-g", "-c", f"/src/{rel_src}", "-o", obj_path]
    for inc in include_dirs:
        argv += ["-I", inc]
    r = tc.exec(argv)
    if r.returncode != 0:
        return CompileResult(ok=False, obj_path=None, reason=r.stderr.strip()[:2000])
    return CompileResult(ok=True, obj_path=obj_path, reason=None)
