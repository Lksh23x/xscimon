"""Load seed data (domains, skill prompts, tracked accounts, keyword rules) into SQLite.

    uv run python scripts/seed.py                 # into the DB from config.yaml
    uv run python scripts/seed.py --db other.db   # into a specific file

Safe to re-run: domains and keyword rules are updated by name, accounts are added
if missing. Edit the files under seed/ and run again to apply changes.
"""
import argparse
from pathlib import Path

from sqlmodel import Session, create_engine

from xscimon.config import get_config
from xscimon.database import init_db
from xscimon.services import SeedService

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, default=ROOT / get_config()["database"]["path"],
                        help="SQLite file to seed (default: database.path in config.yaml)")
    parser.add_argument("--seed-dir", type=Path, default=ROOT / "seed",
                        help="directory containing seed.yaml (default: seed/)")
    args = parser.parse_args()

    args.db.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{args.db}")
    init_db(engine)
    with Session(engine) as session:
        summary = SeedService(session).load(args.seed_dir)

    print(f"Seeded {args.db}")
    for d in summary["domains"]:
        print(f"  domain  {d['name']!r}: {d['accounts']} accounts")
    print(f"  keyword rules: {summary['keywords']}")


if __name__ == "__main__":
    main()
