"""Command line entry point.

    python -m opendoor_telemetry.cli init-db
    python -m opendoor_telemetry.cli ingest sec
    python -m opendoor_telemetry.cli ingest footnotes --limit 4
    python -m opendoor_telemetry.cli ingest redfin --dataset metro
    python -m opendoor_telemetry.cli ingest fred
    python -m opendoor_telemetry.cli ingest listings --limit 25
    python -m opendoor_telemetry.cli ingest all

    python -m opendoor_telemetry.cli verify sec        # no DB required
    python -m opendoor_telemetry.cli verify footnotes  # no DB required
    python -m opendoor_telemetry.cli verify listings   # no DB required
"""

from __future__ import annotations

import argparse
import logging
import sys


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)-38s %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)


# --------------------------------------------------------------------- #
# ingest
# --------------------------------------------------------------------- #
def cmd_ingest(args: argparse.Namespace) -> int:
    source = args.source

    if source in ("sec", "all"):
        from .sources import edgar_facts
        edgar_facts.ingest()

    if source in ("footnotes", "all"):
        from .sources import edgar_footnotes
        edgar_footnotes.ingest(limit=args.limit or 8, all_periods=args.all_periods)

    if source in ("redfin", "all"):
        from .sources import redfin_bulk
        datasets = [args.dataset] if args.dataset else ["metro", "weekly"]
        for ds in datasets:
            redfin_bulk.ingest(ds, force=args.force)

    if source in ("fred", "all"):
        from .sources import fred_macro
        fred_macro.ingest()

    if source in ("listings", "all"):
        from .sources import opendoor_listings
        opendoor_listings.ingest(limit=args.limit)

    return 0


def cmd_init_db(args: argparse.Namespace) -> int:
    from .db import apply_schema
    apply_schema()
    print("schema applied")
    return 0


# --------------------------------------------------------------------- #
# verify -- network only, no database needed
# --------------------------------------------------------------------- #
def cmd_verify(args: argparse.Namespace) -> int:
    target = args.target

    if target in ("sec", "all"):
        from .sources import edgar_facts
        snap = edgar_facts.latest_snapshot()
        print(f"\n=== SEC XBRL :: {snap.get('entity')} @ {snap.get('period_end')} ===")
        for concept, info in snap.items():
            if not isinstance(info, dict):
                continue
            val = info["value"]
            shown = f"{val:>18,.0f}" if isinstance(val, (int, float)) else f"{'--':>18}"
            print(f"  {concept:<24} {shown}   [{info['tag'] or 'no tag matched'}]")
        tnw = snap.get("tangible_net_worth")
        if tnw is not None:
            print(f"  {'tangible_net_worth':<24} {tnw:>18,.0f}   [derived]")

    if target in ("footnotes", "all"):
        from .sources import edgar_footnotes
        df = edgar_footnotes.preview()
        print("\n=== EDGAR footnote R-file :: credit facilities ===")
        cols = [
            "facility_name", "facility_group", "period_end", "borrowing_capacity",
            "outstanding_current", "outstanding_noncurrent", "wtd_avg_rate",
        ]
        print(df[[c for c in cols if c in df.columns]].to_string(index=False))

    if target in ("listings", "all"):
        from .sources import opendoor_listings
        rows = opendoor_listings.preview(n=args.limit or 3)
        print("\n=== Opendoor listings ===")
        for r in rows:
            print(
                f"  {r['street']}, {r['city']} {r['state']}  "
                f"list=${r['listPrice']:,}  dom={r['daysOnMarket']}  "
                f"state={r['listingState']}"
                if r.get("listPrice") else f"  {r}"
            )

    if target in ("redfin", "all"):
        from .sources import redfin_bulk
        print("\n=== Redfin bulk (metro) ===")
        print(redfin_bulk.summarize("metro"))

    if target in ("fred", "all"):
        from .sources import fred_macro
        print("\n=== FRED ===")
        print(fred_macro.preview("MORTGAGE30US"))

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="opendoor_telemetry")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init-db", help="apply sql/*.sql")
    p_init.set_defaults(func=cmd_init_db)

    p_ing = sub.add_parser("ingest", help="run an ingestion source")
    p_ing.add_argument(
        "source",
        choices=["sec", "footnotes", "redfin", "fred", "listings", "all"],
    )
    p_ing.add_argument("--limit", type=int, default=None)
    p_ing.add_argument("--dataset", choices=sorted(["metro", "weekly", "county", "city", "zip", "state"]))
    p_ing.add_argument("--force", action="store_true", help="ignore the download cache")
    p_ing.add_argument("--all-periods", action="store_true",
                       help="footnotes: also ingest the comparative prior-period column")
    p_ing.set_defaults(func=cmd_ingest)

    p_ver = sub.add_parser("verify", help="check a source end to end without a database")
    p_ver.add_argument(
        "target",
        choices=["sec", "footnotes", "redfin", "fred", "listings", "all"],
    )
    p_ver.add_argument("--limit", type=int, default=None)
    p_ver.set_defaults(func=cmd_verify)

    args = parser.parse_args(argv)
    _setup_logging(args.verbose)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
