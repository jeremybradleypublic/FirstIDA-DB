# create_disasm_dataset

Builds a dataset of `(assembly, C/C++ source)` **function pairs**: `X` = x86-64
`objdump` disassembly of one function, `Y` = the original source function.
See `docs/DESIGN.md` for the full design and `docs/superpowers/plans/` for the plans.

## Prerequisites

- macOS with [Homebrew](https://brew.sh).
- Everything else is installed/provisioned automatically:
  - `brew install colima docker` (one-time; the pipeline starts Colima and builds
    the toolchain image on first run).
- Python env:
  ```bash
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
  ```

> Note: repositories to process must live under your home directory (`$HOME`).
> Colima only virtiofs-mounts `$HOME` by default, so a repo outside it (e.g. under
> the OS temp dir) would mount empty inside the toolchain container.

## Reproduce the zlib dataset (end-to-end)

```bash
git clone https://github.com/madler/zlib first_example/zlib   # sample repo (gitignored)
.venv/bin/python -m pipeline.run_pipeline first_example/zlib --repo zlib
```

This auto-starts the Linux x86-64 toolchain container (GCC + Clang + binutils),
compiles every translation unit at `-O0/-O1/-O2/-O3/-Os` with both compilers,
disassembles with `objdump`, pairs each symbol back to its source function, and
writes unique pairs into `dataset/pairs.db`.

Reference run (zlib): **642 pairs**, 69 distinct functions, all five opt levels,
both `gcc-12.2.0` and `clang-14.0.6`; 50 translation units that don't compile in
isolation (mostly `contrib/` needing platform headers) are logged to `skipped`.

## Point it at any other repo

```bash
.venv/bin/python -m pipeline.run_pipeline /path/to/any/c_or_cpp/repo --repo myrepo
```

Files that don't compile in isolation are logged to the `skipped` table and never
abort the run. Re-running is idempotent (dedup via `pairs.pair_hash`).

## Database

SQLite at `dataset/pairs.db` (gitignored — reproducible via the pipeline).

- `pairs(repo,file_path,func_name,signature,lang,arch,opt_level,obj_format,compiler,source_text,asm_text,...,pair_hash UNIQUE)`
- `skipped(repo,file_path,opt_level,reason)`
- `repos(url,commit_sha,license,status,n_pairs,processed_at)` — used by the Phase-2 scraper.

Example query:
```bash
sqlite3 dataset/pairs.db \
  "SELECT func_name,opt_level,compiler FROM pairs WHERE repo='zlib' LIMIT 10;"
```

## Testing

```bash
.venv/bin/pytest -v            # unit tests always run; integration tests need Docker
```
Integration tests auto-skip when Docker/Colima is unavailable; start it with
`colima start` (or `colima start --vm-type=vz --vz-rosetta` for faster x86-64 emulation).

## Troubleshooting

- **Colima won't start:** `colima delete && colima start`.
- **Rebuild the toolchain image:** `docker rmi disasm-toolchain:latest` then re-run.
- **x86-64 emulation:** builds run under `--platform linux/amd64` (Rosetta); we only
  compile/disassemble, never execute, so this only affects compile latency.
