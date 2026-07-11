import argparse
import os

import pipeline.env as env
import pipeline.extract as extract
import pipeline.compile as compile_mod
import pipeline.disasm as disasm
import pipeline.pair as pair
import pipeline.store as store

_SRC_EXT = (".c", ".cc", ".cpp", ".cxx", ".c++", ".C")


def find_sources(repo_dir: str):
    out = []
    for root, _dirs, files in os.walk(repo_dir):
        for f in files:
            if f.endswith(_SRC_EXT):
                out.append(os.path.relpath(os.path.join(root, f), repo_dir))
    return sorted(out)


def include_dirs_for(repo_dir: str):
    incs = {"/src"}
    for root, _dirs, files in os.walk(repo_dir):
        if any(f.endswith((".h", ".hpp", ".hh")) for f in files):
            rel = os.path.relpath(root, repo_dir)
            incs.add("/src" if rel == "." else f"/src/{rel}")
    return sorted(incs)


def run(repo_dir, repo=None, db_path="dataset/pairs.db",
        compilers=("gcc", "clang"), opt_levels=("O0", "O1", "O2", "O3", "Os"),
        progress=None, journal=None):
    repo = repo or os.path.basename(os.path.abspath(repo_dir))
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    conn = store.connect(db_path)
    store.init_schema(conn)

    sources = find_sources(repo_dir)
    incs = include_dirs_for(repo_dir)
    tc = env.start_toolchain(repo_dir, journal=journal)
    stats = {"pairs": 0, "skipped": 0, "files": len(sources)}
    labels = {}
    if journal:
        journal.event(f"pipeline {repo}: {len(sources)} source file(s), "
                      f"{len(compilers)}x{len(opt_levels)} compiler/opt matrix")
    try:
        for i, rel in enumerate(sources):
            if progress:
                progress({"type": "file", "file": rel, "i": i + 1, "n": len(sources)})
            if journal:
                journal.event(f"file {i + 1}/{len(sources)}: {rel}")
            lang = extract.lang_for(rel)
            if lang is None:
                continue
            records = extract.extract_functions(os.path.join(repo_dir, rel))
            if not records:
                continue
            for compiler in compilers:
                if (compiler, lang) not in labels:
                    labels[(compiler, lang)] = compile_mod.compiler_label(tc, compiler, lang)
                label = labels[(compiler, lang)]
                for opt in opt_levels:
                    res = compile_mod.compile_tu(tc, rel, compiler, opt, lang, incs)
                    if not res.ok:
                        if journal:
                            reason1 = (res.reason or "").splitlines()[0][:160] if res.reason else ""
                            journal.event(f"{compiler} {opt}: {rel} — {reason1}",
                                          level="warn")
                        store.record_skip(conn, repo=repo, file_path=rel,
                                          opt_level=opt, reason=res.reason)
                        stats["skipped"] += 1
                        continue
                    asm = disasm.disassemble(tc, res.obj_path)
                    for p in pair.pair_functions(records, asm):
                        if store.insert_pair(conn, repo=repo, file_path=rel,
                                             func_name=p.func_name, signature=p.signature,
                                             lang=p.lang, arch="x86_64", opt_level=opt,
                                             obj_format="elf", compiler=label,
                                             source_text=p.source_text, asm_text=p.asm_text):
                            stats["pairs"] += 1
    finally:
        tc.stop()
    if journal:
        journal.event(f"pipeline {repo}: {stats['pairs']} pairs, "
                      f"{stats['skipped']} skipped")
    return stats


def main():
    ap = argparse.ArgumentParser(description="Extract (asm, source) function pairs from a repo.")
    ap.add_argument("repo_dir")
    ap.add_argument("--db", default="dataset/pairs.db")
    ap.add_argument("--repo", default=None)
    args = ap.parse_args()
    stats = run(args.repo_dir, repo=args.repo, db_path=args.db)
    print(f"pairs={stats['pairs']} skipped={stats['skipped']} files={stats['files']}")


if __name__ == "__main__":
    main()
