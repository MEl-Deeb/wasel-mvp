from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .core import DEFAULT_CSV, DEFAULT_DB, DEFAULT_DASHBOARD, WaselService


def emit(value: Any, as_json: bool = False) -> None:
    if as_json:
        print(json.dumps(value, ensure_ascii=False, indent=2))
        return
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                issues = ", ".join(item.get("issues", [])) or "none"
                print(
                    f"{item.get('order_id', '—'):10} | {item.get('status', '—'):18} | "
                    f"risk {item.get('risk_score', 0):3} | issues: {issues}"
                )
            else:
                print(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            print(f"{key}: {item}")
    else:
        print(value)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Wasel COD operations MVP")
    root.add_argument("--db", default=str(DEFAULT_DB), help="SQLite database path")
    root.add_argument("--json", action="store_true", help="Return machine-readable JSON")
    sub = root.add_subparsers(dest="command", required=True)

    reset = sub.add_parser("reset", help="Reset the demo database from a CSV")
    reset.add_argument("--csv", default=str(DEFAULT_CSV))

    load = sub.add_parser("import", help="Import or update orders from a CSV")
    load.add_argument("csv")

    sub.add_parser("scan", help="Validate and prioritize every order")
    listing = sub.add_parser("list", help="List the order queue")
    listing.add_argument("--status")

    order = sub.add_parser("order", help="Show one order")
    order.add_argument("order_id")
    plan = sub.add_parser("plan", help="Return the next customer message and allowed actions")
    plan.add_argument("order_id")

    address = sub.add_parser("update-address", help="Save a corrected address")
    address.add_argument("order_id")
    address.add_argument("--address", required=True)
    address.add_argument("--landmark", required=True)

    confirm = sub.add_parser("confirm", help="Confirm an order")
    confirm.add_argument("order_id")
    failed = sub.add_parser("fail-delivery", help="Record a failed delivery")
    failed.add_argument("order_id")
    failed.add_argument("--reason", required=True)
    reschedule = sub.add_parser("reschedule", help="Reschedule a failed delivery")
    reschedule.add_argument("order_id")
    reschedule.add_argument("--date", required=True)
    reschedule.add_argument("--window", required=True)
    cancel = sub.add_parser("cancel", help="Cancel an order")
    cancel.add_argument("order_id")
    cancel.add_argument("--reason", required=True)
    deliver = sub.add_parser("deliver", help="Mark an order delivered")
    deliver.add_argument("order_id")

    sub.add_parser("metrics", help="Show measurable business impact")
    sub.add_parser("audit", help="Show the append-only audit log")
    dashboard = sub.add_parser("dashboard", help="Generate a standalone HTML dashboard")
    dashboard.add_argument("--output", default=str(DEFAULT_DASHBOARD))
    return root


def execute(args: argparse.Namespace) -> Any:
    service = WaselService(Path(args.db))
    command = args.command
    if command == "reset":
        return {"imported_orders": service.reset(args.csv), "database": str(Path(args.db).resolve())}
    if command == "import":
        return {"imported_orders": service.import_csv(args.csv)}
    if command == "scan":
        return [item.as_dict() for item in service.scan()]
    if command == "list":
        return service.list_orders(args.status)
    if command == "order":
        return service.get_order(args.order_id)
    if command == "plan":
        return service.conversation_plan(args.order_id)
    if command == "update-address":
        return service.update_address(args.order_id, args.address, args.landmark)
    if command == "confirm":
        return service.confirm(args.order_id)
    if command == "fail-delivery":
        return service.fail_delivery(args.order_id, args.reason)
    if command == "reschedule":
        return service.reschedule(args.order_id, args.date, args.window)
    if command == "cancel":
        return service.cancel(args.order_id, args.reason)
    if command == "deliver":
        return service.deliver(args.order_id)
    if command == "metrics":
        return service.metrics()
    if command == "audit":
        return service.audit_log()
    if command == "dashboard":
        return {"dashboard": str(service.generate_dashboard(args.output))}
    raise ValueError(f"Unknown command: {command}")


def main() -> None:
    args = parser().parse_args()
    try:
        emit(execute(args), args.json)
    except (ValueError, KeyError, FileNotFoundError) as exc:
        if args.json:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        else:
            print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()

