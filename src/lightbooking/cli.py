import argparse
import json
import os
from pathlib import Path
import sys

from .checkout_reconcile.service import evidence, export_table
from .hold_registry.service import list_releases, register
from .engine import ROOT, plan
from .settings import DEFAULT_BUDGET, DEFAULT_DAY, PROJECT_NAME


def _arguments():
    parser = argparse.ArgumentParser(description=PROJECT_NAME)
    commands = parser.add_subparsers(dest="command", required=True)
    for verb in ("plan", "inspect", "export", "register"):
        command = commands.add_parser(verb)
        command.add_argument("--snapshot", type=int, default=DEFAULT_DAY)
        command.add_argument("--capacity", type=int, default=DEFAULT_BUDGET)
        command.add_argument("--packet", type=Path)
        if verb == "inspect":
            command.add_argument(
                "step",
                choices=[
                    "ingestion",
                    "features",
                    "model",
                    "replay",
                    "shift",
                    "resources",
                ],
            )
        elif verb == "export":
            command.add_argument("destination", type=Path)
        elif verb == "register":
            command.add_argument("--expected", type=int, required=True)
            command.add_argument(
                "--run-id", required=True, help="待登记方案返回的完整运行标识"
            )
        else:
            command.add_argument("--summary", action="store_true")
    history = commands.add_parser("history")
    history.add_argument("--limit", type=int, default=30)
    history.add_argument("--before", type=int)
    return parser.parse_args()


def _payload(raw):
    return json.loads(raw.read_text(encoding="utf-8-sig")) if raw else None


def _json(value):
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)


def main():
    options = _arguments()
    db = Path(os.environ.get("WORKSHOP_DB", ROOT / "var" / "register.sqlite3"))
    try:
        if options.command == "history":
            from dataclasses import asdict

            print(
                _json(
                    [
                        asdict(row)
                        for row in list_releases(db, options.limit, options.before)
                    ]
                )
            )
            return 0
        result = plan(
            _payload(options.packet), as_of=options.snapshot, capacity=options.capacity
        )
        if options.command == "inspect":
            print(_json(evidence(result.body, options.step)))
        elif options.command == "export":
            options.destination.write_text(
                export_table(result.body), encoding="utf-8-sig"
            )
            print(
                _json(
                    {
                        "run_id": result.digest,
                        "records": result.quantity,
                        "target": str(options.destination),
                    }
                )
            )
        elif options.command == "register":
            if options.run_id != result.digest:
                raise ValueError("待登记证据已经变化，请按新方案重新核对")
            entry = register(db, result, options.expected)
            print(
                _json(
                    {
                        "generation": entry.generation,
                        "run_id": entry.run_id,
                        "replayed": entry.replayed,
                    }
                )
            )
        elif options.summary:
            print(
                _json(
                    {
                        "project": PROJECT_NAME,
                        "run_id": result.digest,
                        **result.body["summary"],
                    }
                )
            )
        else:
            print(_json(result.body))
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
