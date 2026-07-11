"""Run the git scraper (harvester) and the synthetic generator concurrently
under ONE unified live dashboard — two panels side by side, split by a border
down the middle of the terminal. Both write the same dataset/pairs.db in
parallel (WAL + busy_timeout); each keeps its own journal. When both finish the
source split is printed and the HTML gallery opens.

  python -m pipeline.run_both                      # 10 repos + 200 gen funcs
  python -m pipeline.run_both --repos 30 --gen 500 --route hybrid
"""
import argparse

import pipeline.harvest as harvest
import pipeline.generate as generate
import pipeline.dashboard as dashboard
import pipeline.gallery as gallery
import pipeline.store as store


def main():
    ap = argparse.ArgumentParser(
        description="Unified live dashboard: git scraper + generator in parallel.")
    ap.add_argument("--repos", type=int, default=10, help="repos for the scraper")
    ap.add_argument("--gen", type=int, default=200, help="functions per generator route")
    ap.add_argument("--route", choices=("direct", "hybrid", "both"), default="both")
    ap.add_argument("--db", default="dataset/pairs.db")
    ap.add_argument("--max-files", type=int, default=300)
    ap.add_argument("--no-gallery", action="store_true")
    args = ap.parse_args()

    def scraper(emit):
        return harvest.harvest(db_path=args.db, limit=args.repos, emit=emit,
                               discover_first=True, target=args.repos,
                               max_files=args.max_files)

    def generator(emit):
        return generate.generate(count=args.gen, route=args.route,
                                 db_path=args.db, emit=emit)

    dashboard.run_split_dashboard([
        ("git scraper", "cyan", scraper),
        ("generator", "magenta", generator),
    ])

    conn = store.connect(args.db)
    split = dict(conn.execute(
        "SELECT source_system, COUNT(*) FROM pairs_labeled GROUP BY source_system"
    ).fetchall())
    conn.close()
    print(f"source split: {split}")
    print("sources list: dataset/sources_used.tsv")
    if not args.no_gallery:
        out = gallery.build_gallery(db_path=args.db)
        if generate._open_path(out):
            print(f"gallery: opened {out}")
        else:
            print(f"gallery: {out}")


if __name__ == "__main__":
    main()
