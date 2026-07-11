# Database Map: pairs

This database contains 3 units across 1 themes: Disassembly Pair Corpus.

## Themes
### Disassembly Pair Corpus (3 units)
The complete FirstIDA-DB dataset generation record: ~85K matched (C source, x86-64 disassembly) function pairs with build metadata and content hashes, the ~14K-row log of source files that failed to compile, and the 116-repo provenance ledger of upstream GitHub projects. Together these three tables record what was produced, what was dropped, and where it came from.
- pairs: (structural only - run /dbgraph resume to enrich)
- repos: 116 rows describing the upstream GitHub repositories the dataset is built from: url, commit_sha, license, processing status (done/queued/failed), n_pairs produced, processed_at timestamp, failure reason, and stars. This is the provenance/catalog of source projects.
- skipped: 13,688 rows recording source files that failed to compile during dataset generation, keyed by repo/file_path/opt_level with a free-text reason holding the compiler error output (missing headers, invalid conversions, unsupported vector intrinsics, etc.). This is the failure/rejection log complementing the successful pairs.

## Connections that matter

## How to navigate
Query the `_dbgraph_units` table for per-table gists and themes; `_dbgraph_edges` lists how tables join (foreign_key / value_overlap relations name the join columns); `_dbgraph_themes` has theme summaries.