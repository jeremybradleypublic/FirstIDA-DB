# Database Map: pairs

This database contains 3 units across 1 themes: Disassembly Pair Corpus.

## Themes
### Disassembly Pair Corpus (3 units)
The complete FirstIDA-DB dataset: matched (C/C++ source, x86-64 disassembly) function pairs, the log of translation units that failed to compile, and the provenance ledger for future large-scale crawling. Together these three tables record what was produced, what was dropped, and where it came from.
- pairs: The core dataset table: 642 rows of matched (C/C++ source, x86-64 disassembly) function pairs from zlib, each tagged with compiler, optimization level, and dedup hash.
- repos: An empty provenance ledger meant to track repositories processed in a future large-scale GitHub crawl (Phase 2), recording URL, commit SHA, license, status, and pairs contributed.
- skipped: A failure log of 50 translation units that could not be compiled during the build sweep, recording the repo, file, opt level, and compiler error reason.

## Connections that matter

## How to navigate
Query the `_dbgraph_units` table for per-table gists and themes; `_dbgraph_edges` lists how tables join (foreign_key / value_overlap relations name the join columns); `_dbgraph_themes` has theme summaries.