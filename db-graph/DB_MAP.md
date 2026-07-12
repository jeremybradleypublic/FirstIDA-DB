# Database Map: pairs

This database contains 4 units across 4 themes: Disassembly Pair Corpus, Repo Provenance, Labeled Training View, Skipped Compilations (plus 45 facets).

## Themes
### Disassembly Pair Corpus (1 units)
The pairs table and its compilation-matrix facets: compilers, optimization levels, languages, origins.
- pairs: The core dataset: 110K source-function/disassembly pairs harvested from 100+ C/C++ repos, compiled at six optimization levels with gcc-12.2.0 and clang-14.0.6 to x86_64 ELF; each row carries source_text, asm_text, and dedup hashes.
  - Sub-branch: disassembly-pairs (1 units)

### Repo Provenance (1 units)
Harvested repositories with license mix and pipeline status.
- repos: Provenance registry of the 116 harvested GitHub repos: url, pinned commit, license (mostly MIT/Apache-2.0), pipeline status (done/queued/failed), pair counts and star counts.
  - Sub-branch: provenance (1 units)

### Labeled Training View (1 units)
pairs_labeled view facets adding source_system over the same corpus.
- pairs_labeled: A view over pairs adding source_system (git-scraper vs generator) derived from origin - the training-consumption surface of the same 110K rows.
  - Sub-branch: view (1 units)

### Skipped Compilations (1 units)
Files that failed to compile, spread evenly across optimization levels.
- skipped: Compilation failures log: 16K files that could not be compiled (missing headers, platform intrinsics, node bindings), evenly spread across the five optimization levels; reason holds the raw compiler error.

## Data landscape
- pairs.compiler: gcc-12.2.0 53%, clang-14.0.6 47%, asmjit <1%
- pairs.lang: c 94%, cpp 6%
- pairs.obj_format: elf 100%, rawx86_64 <1%
- pairs.origin: harvest 98%, gen:direct 1%, gen:hybrid <1%
- pairs.session: scrape-20260712T002029Z 14%, gen-20260712T002030Z 1%, scrape-20260711T212132Z <1%, gen-20260711T211742Z <1%
- pairs_labeled.compiler: gcc-12.2.0 53%, clang-14.0.6 47%, asmjit <1%
- pairs_labeled.lang: c 94%, cpp 6%
- pairs_labeled.obj_format: elf 100%, rawx86_64 <1%
- pairs_labeled.origin: harvest 98%, gen:direct 1%, gen:hybrid <1%
- pairs_labeled.source_system: git-scraper 98%, generator 2%
- repos.license: mit 53%, apache-2.0 28%, isc 6%, bsd-2-clause 5%, unlicense 3%, zlib 3%, bsd-3-clause 2%
- repos.reason: [Errno 2] No such file or directory: '/Users/jbradley/.cache/disasm_harvest/dsprenkels__sss/randombytes.c' 1%, too many files (1604) 1%, too many files (325) 1%, too many files (749) 1%
- repos.status: done 59%, queued 38%, failed 3%
- skipped.opt_level: O0 20%, O2 20%, O3 20%, O1 20%, Os 20%
- pairs: obj_format=elf + origin=harvest: 108,586 rows
- pairs: lang=c + obj_format=elf: 103,004 rows
- pairs: lang=c + origin=harvest: 101,771 rows
- pairs_labeled: obj_format=elf + source_system=git-scraper: 108,586 rows
- pairs_labeled: obj_format=elf + origin=harvest: 108,586 rows
- pairs_labeled: source_system=git-scraper + origin=harvest: 108,586 rows
- repos: status=done + license=mit: 32 rows
- repos: status=queued + license=mit: 27 rows
- repos: status=done + license=apache-2.0: 20 rows
- no rows: pairs compiler=asmjit x origin=gen:direct
- no rows: pairs compiler=asmjit x origin=harvest
- no rows: pairs compiler=asmjit x session=scrape-20260711T212132Z
- no rows: pairs_labeled compiler=asmjit x origin=gen:direct
- no rows: pairs_labeled compiler=asmjit x origin=harvest
- no rows: pairs_labeled compiler=clang-14.0.6 x origin=gen:hybrid
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