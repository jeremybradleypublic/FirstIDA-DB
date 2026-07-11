# Database Map: pairs

This database contains 45 units across 4 themes: Disassembly Pair Corpus, Theme 1: pairs & obj_format=elf, Theme 2: pairs_labeled & obj_format=elf, Theme 3: skipped & opt_level=O0.

## Themes
### Disassembly Pair Corpus (1 units)
The complete FirstIDA-DB dataset generation record: ~85K matched (C source, x86-64 disassembly) function pairs with build metadata and content hashes, the ~14K-row log of source files that failed to compile, and the 116-repo provenance ledger of upstream GitHub projects. Together these three tables record what was produced, what was dropped, and where it came from.
- repos: (structural only - run /dbgraph resume to enrich)
  - Sub-branch: [Errno 2] No such file or directory: '/Users/jbradley/.cache/disasm_harvest/dsprenkels__sss/randombytes.c' (10 units)
  - Sub-branch: apache-2.0 (4 units)

### Theme 1: pairs & obj_format=elf (1 units)
- pairs: (structural only - run /dbgraph resume to enrich)
  - Sub-branch: rawx86_64 (7 units)
  - Sub-branch: cpp (6 units)

### Theme 2: pairs_labeled & obj_format=elf (1 units)
- pairs_labeled: (structural only - run /dbgraph resume to enrich)
  - Sub-branch: rawx86_64 (6 units)
  - Sub-branch: c (6 units)

### Theme 3: skipped & opt_level=O0 (1 units)
- skipped: (structural only - run /dbgraph resume to enrich)

## Data landscape
- pairs.compiler: gcc-12.2.0 53%, clang-14.0.6 47%, asmjit 0%
- pairs.lang: c 93%, cpp 7%
- pairs.obj_format: elf 100%, rawx86_64 0%
- pairs.origin: harvest 99%, gen:direct 1%, gen:hybrid 0%
- pairs.session: scrape-20260711T212132Z 0%, gen-20260711T211742Z 0%
- pairs_labeled.compiler: gcc-12.2.0 53%, clang-14.0.6 47%, asmjit 0%
- pairs_labeled.lang: c 93%, cpp 7%
- pairs_labeled.obj_format: elf 100%, rawx86_64 0%
- pairs_labeled.session: scrape-20260711T212132Z 0%, gen-20260711T211742Z 0%
- pairs_labeled.source_system: git-scraper 99%, generator 1%
- repos.license: mit 53%, apache-2.0 28%, isc 6%, bsd-2-clause 5%, unlicense 3%, zlib 3%, bsd-3-clause 2%
- repos.reason: [Errno 2] No such file or directory: '/Users/jbradley/.cache/disasm_harvest/dsprenkels__sss/randombytes.c' 1%, too many files (1604) 1%, too many files (749) 1%
- repos.status: done 51%, queued 47%, failed 3%
- skipped.opt_level: O0 20%, O2 20%, O3 20%, O1 20%, Os 20%
- obj_format=elf + origin=harvest: 93,655 rows
- lang=c + obj_format=elf: 87,259 rows
- lang=c + origin=harvest: 86,840 rows
- obj_format=elf + source_system=git-scraper: 93,655 rows
- lang=c + obj_format=elf: 87,259 rows
- lang=c + source_system=git-scraper: 86,840 rows
- status=queued + license=mit: 33 rows
- status=done + license=mit: 27 rows
- status=done + license=apache-2.0: 19 rows
- no rows: pairs compiler=asmjit x origin=gen:direct
- no rows: pairs compiler=asmjit x origin=harvest
- no rows: pairs compiler=clang-14.0.6 x origin=gen:hybrid
- no rows: pairs_labeled lang=cpp x compiler=asmjit
- no rows: pairs_labeled lang=cpp x obj_format=rawx86_64
- no rows: pairs_labeled lang=cpp x session=gen-20260711T211742Z
- no rows: repos reason=[Errno 2] No such file or directory: '/Users/jbradley/.cache/disasm_harvest/dsprenkels__sss/randombytes.c' x license=apache-2.0
- no rows: repos reason=[Errno 2] No such file or directory: '/Users/jbradley/.cache/disasm_harvest/dsprenkels__sss/randombytes.c' x license=bsd-2-clause
- no rows: repos reason=[Errno 2] No such file or directory: '/Users/jbradley/.cache/disasm_harvest/dsprenkels__sss/randombytes.c' x license=bsd-3-clause

## Connections that matter
- pairs <-> repos via planned provenance source for future pairs [AMBIGUOUS]
- pairs <-> pairs_labeled via shared_column:arch [EXTRACTED]
- pairs <-> skipped via shared_column:file_path [EXTRACTED]
- skipped <-> repos via shared_column:reason [EXTRACTED]
- skipped <-> pairs_labeled via shared_column:file_path [EXTRACTED]

## How to navigate
Query the `_dbgraph_units` table for per-table gists and themes; `_dbgraph_edges` lists how tables join (foreign_key / value_overlap relations name the join columns); `_dbgraph_themes` has theme summaries. Rows with kind='facet' carry per-value row counts and percentages in their gists.