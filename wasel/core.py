from __future__ import annotations

import csv
import html
import json
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "wasel.db"
DEFAULT_CSV = ROOT / "data" / "sample_orders.csv"
DEFAULT_DASHBOARD = ROOT / "dashboard.html"

VALID_STATUSES = {
    "new",
    "needs_confirmation",
    "address_needed",
    "needs_review",
    "confirmed",
    "failed_delivery",
    "rescheduled",
    "cancelled",
    "delivered",
}

# Statuses that mean the order is still waiting on someone (customer or operator)
# to act. The pending penalty is keyed to these rather than to "new" alone, because
# scan() rewrites an order's status to its derived pending state: keying on "new"
# made the penalty vanish after the first scan and dropped the risk score without
# any operator action.
PENDING_STATUSES = {
    "new",
    "needs_confirmation",
    "address_needed",
    "needs_review",
}

# Statuses an operator has closed out. Their risk score is set once by the closing
# transition and is never recomputed by scan, so no score moves without human action.
RESOLVED_STATUSES = {
    "confirmed",
    "rescheduled",
    "delivered",
    "cancelled",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def digits(value: str | None) -> str:
    return "".join(ch for ch in (value or "") if ch.isdigit())


def address_is_complete(address: str | None) -> bool:
    value = (address or "").strip()
    return len(value) >= 12 and any(ch.isdigit() for ch in value)


def phone_is_valid(phone: str | None) -> bool:
    return 10 <= len(digits(phone)) <= 13


@dataclass
class ScanResult:
    order_id: str
    status: str
    risk_score: int
    issues: list[str]
    duplicate_of: str | None
    next_action: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "order_id": self.order_id,
            "status": self.status,
            "risk_score": self.risk_score,
            "issues": self.issues,
            "duplicate_of": self.duplicate_of,
            "next_action": self.next_action,
        }


class WaselService:
    def __init__(self, db_path: Path | str = DEFAULT_DB):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._create_schema()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def session(self):
        connection = self.connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _create_schema(self) -> None:
        with self.session() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS orders (
                    order_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    customer_name TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    address TEXT NOT NULL DEFAULT '',
                    landmark TEXT NOT NULL DEFAULT '',
                    amount_egp REAL NOT NULL,
                    shipping_cost_egp REAL NOT NULL,
                    status TEXT NOT NULL,
                    preferred_date TEXT NOT NULL DEFAULT '',
                    preferred_window TEXT NOT NULL DEFAULT '',
                    items TEXT NOT NULL DEFAULT '',
                    language TEXT NOT NULL DEFAULT 'ar',
                    risk_score INTEGER NOT NULL DEFAULT 0,
                    issues TEXT NOT NULL DEFAULT '[]',
                    duplicate_of TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    order_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    from_status TEXT,
                    to_status TEXT,
                    details TEXT NOT NULL DEFAULT '{}',
                    minutes_saved REAL NOT NULL DEFAULT 0,
                    revenue_protected_egp REAL NOT NULL DEFAULT 0,
                    recovered_revenue_egp REAL NOT NULL DEFAULT 0,
                    avoided_cost_egp REAL NOT NULL DEFAULT 0
                );
                """
            )

    def reset(self, csv_path: Path | str = DEFAULT_CSV) -> int:
        with self.session() as db:
            db.execute("DELETE FROM events")
            db.execute("DELETE FROM orders")
        return self.import_csv(csv_path)

    def import_csv(self, csv_path: Path | str) -> int:
        path = Path(csv_path)
        required = {
            "order_id",
            "created_at",
            "customer_name",
            "phone",
            "address",
            "landmark",
            "amount_egp",
            "shipping_cost_egp",
            "status",
            "preferred_date",
            "preferred_window",
            "items",
            "language",
        }
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            missing = required - set(reader.fieldnames or [])
            if missing:
                raise ValueError(f"CSV is missing columns: {', '.join(sorted(missing))}")
            rows = list(reader)

        now = utc_now()
        with self.session() as db:
            for row in rows:
                status = row["status"].strip() or "new"
                if status not in VALID_STATUSES:
                    raise ValueError(f"Invalid status {status!r} for {row['order_id']}")
                db.execute(
                    """
                    INSERT INTO orders (
                        order_id, created_at, customer_name, phone, address, landmark,
                        amount_egp, shipping_cost_egp, status, preferred_date,
                        preferred_window, items, language, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(order_id) DO UPDATE SET
                        created_at=excluded.created_at,
                        customer_name=excluded.customer_name,
                        phone=excluded.phone,
                        address=excluded.address,
                        landmark=excluded.landmark,
                        amount_egp=excluded.amount_egp,
                        shipping_cost_egp=excluded.shipping_cost_egp,
                        status=excluded.status,
                        preferred_date=excluded.preferred_date,
                        preferred_window=excluded.preferred_window,
                        items=excluded.items,
                        language=excluded.language,
                        updated_at=excluded.updated_at
                    """,
                    (
                        row["order_id"].strip(),
                        row["created_at"].strip(),
                        row["customer_name"].strip(),
                        row["phone"].strip(),
                        row["address"].strip(),
                        row["landmark"].strip(),
                        float(row["amount_egp"]),
                        float(row["shipping_cost_egp"]),
                        status,
                        row["preferred_date"].strip(),
                        row["preferred_window"].strip(),
                        row["items"].strip(),
                        (row["language"].strip() or "ar"),
                        now,
                    ),
                )
        return len(rows)

    def _rows(self) -> list[dict[str, Any]]:
        with self.session() as db:
            rows = db.execute("SELECT * FROM orders ORDER BY created_at, order_id").fetchall()
        return [self._decode_order(dict(row)) for row in rows]

    @staticmethod
    def _decode_order(order: dict[str, Any]) -> dict[str, Any]:
        if isinstance(order.get("issues"), str):
            order["issues"] = json.loads(order["issues"] or "[]")
        return order

    def get_order(self, order_id: str) -> dict[str, Any]:
        with self.session() as db:
            row = db.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
        if row is None:
            raise KeyError(f"Order {order_id!r} was not found")
        return self._decode_order(dict(row))

    def scan(self) -> list[ScanResult]:
        rows = self._rows()
        seen: dict[tuple[str, float, str], str] = {}
        results: list[ScanResult] = []

        with self.session() as db:
            for order in rows:
                issues: list[str] = []
                risk = 0
                duplicate_of: str | None = None

                if not phone_is_valid(order["phone"]):
                    issues.append("invalid_phone")
                    risk += 50
                if not address_is_complete(order["address"]):
                    issues.append("incomplete_address")
                    risk += 40
                if not order["landmark"].strip():
                    issues.append("missing_landmark")
                    risk += 10

                key = (digits(order["phone"]), float(order["amount_egp"]), order["items"].lower())
                if key in seen:
                    issues.append("possible_duplicate")
                    duplicate_of = seen[key]
                    risk += 60
                else:
                    seen[key] = order["order_id"]

                if order["status"] in PENDING_STATUSES:
                    risk += 15
                if order["status"] == "failed_delivery":
                    risk += 45
                    issues.append("failed_delivery")
                if float(order["amount_egp"]) >= 2000:
                    risk += 10
                    issues.append("high_value")

                risk = min(risk, 100)
                status = order["status"]
                if status in PENDING_STATUSES:
                    if duplicate_of:
                        status = "needs_review"
                    elif "invalid_phone" in issues:
                        status = "needs_review"
                    elif "incomplete_address" in issues:
                        status = "address_needed"
                    else:
                        status = "needs_confirmation"

                if status in RESOLVED_STATUSES:
                    # An operator already closed this order: keep the risk and issue
                    # snapshot the closing transition wrote, so a scan can never
                    # move the score of an order nobody is working on.
                    risk = int(order["risk_score"])
                    issues = list(order["issues"])
                    next_action = self._next_action(status, issues)
                    results.append(
                        ScanResult(
                            order["order_id"], status, risk, issues, order["duplicate_of"], next_action
                        )
                    )
                    continue

                next_action = self._next_action(status, issues)
                db.execute(
                    """
                    UPDATE orders
                    SET status=?, risk_score=?, issues=?, duplicate_of=?, updated_at=?
                    WHERE order_id=?
                    """,
                    (status, risk, json.dumps(issues), duplicate_of, utc_now(), order["order_id"]),
                )
                results.append(
                    ScanResult(order["order_id"], status, risk, issues, duplicate_of, next_action)
                )
        return sorted(results, key=lambda item: (-item.risk_score, item.order_id))

    @staticmethod
    def _next_action(status: str, issues: Iterable[str]) -> str:
        issue_set = set(issues)
        if "possible_duplicate" in issue_set:
            return "Ask the operator to review the possible duplicate; do not contact the customer yet."
        if "invalid_phone" in issue_set:
            return "Ask the operator for a valid customer phone number."
        if status == "address_needed":
            return "Ask for building number, street, area, and a nearby landmark."
        if status == "failed_delivery":
            return "Offer a new delivery date and time window."
        if status == "needs_confirmation":
            return "Ask the customer to confirm the order total, address, and availability."
        if status in {"confirmed", "rescheduled"}:
            return "No customer action is required; prepare the order for delivery."
        if status == "delivered":
            return "No action is required; the order has been delivered."
        if status == "cancelled":
            return "No action is required; the order is cancelled."
        return "Escalate to the operator."

    def conversation_plan(self, order_id: str) -> dict[str, Any]:
        order = self.get_order(order_id)
        language = order["language"]
        status = order["status"]
        first_name = order["customer_name"].split()[0]
        if status == "address_needed":
            message_ar = f"أهلاً {first_name}، لتأكيد طلب {order_id} محتاجين رقم العمارة والشارع والمنطقة وأقرب علامة مميزة."
            message_en = f"Hi {first_name}, to confirm order {order_id}, please send the building number, street, area, and a nearby landmark."
        elif status == "failed_delivery":
            message_ar = f"أهلاً {first_name}، تعذر تسليم طلب {order_id}. تحب نعيد التوصيل في أي يوم وفترة؟"
            message_en = f"Hi {first_name}, delivery of order {order_id} was unsuccessful. Which date and time window should we try again?"
        elif status == "needs_review":
            message_ar = "هذه الحالة تحتاج مراجعة موظف المتجر قبل التواصل مع العميل."
            message_en = "An operator must review this order before contacting the customer."
        elif status == "needs_confirmation":
            message_ar = f"أهلاً {first_name}، بنأكد طلب {order_id} بقيمة {order['amount_egp']:.0f} جنيه. هل العنوان والطلب صحيحين؟"
            message_en = f"Hi {first_name}, please confirm order {order_id} for EGP {order['amount_egp']:.0f}. Are the order and delivery address correct?"
        else:
            message_ar = f"حالة طلب {order_id} الحالية هي: {status}."
            message_en = f"Order {order_id} is currently {status}."
        return {
            "order_id": order_id,
            "status": status,
            "language": language,
            "suggested_message": message_ar if language == "ar" else message_en,
            "message_ar": message_ar,
            "message_en": message_en,
            "allowed_actions": self.allowed_actions(status),
        }

    @staticmethod
    def allowed_actions(status: str) -> list[str]:
        mapping = {
            "address_needed": ["update-address", "cancel"],
            "needs_confirmation": ["confirm", "cancel"],
            "failed_delivery": ["reschedule", "cancel"],
            "needs_review": ["operator-review", "cancel"],
            "confirmed": ["fail-delivery", "deliver"],
            "rescheduled": ["fail-delivery", "deliver"],
        }
        return mapping.get(status, [])

    def _transition(
        self,
        order_id: str,
        to_status: str,
        event_type: str,
        details: dict[str, Any] | None = None,
        minutes_saved: float = 0,
        revenue_protected: float = 0,
        recovered_revenue: float = 0,
        avoided_cost: float = 0,
    ) -> dict[str, Any]:
        if to_status not in VALID_STATUSES:
            raise ValueError(f"Invalid target status: {to_status}")
        order = self.get_order(order_id)
        resolved = to_status in RESOLVED_STATUSES
        with self.session() as db:
            db.execute(
                """
                UPDATE orders
                SET status=?, updated_at=?,
                    risk_score=CASE WHEN ? THEN 0 ELSE risk_score END,
                    issues=CASE WHEN ? THEN '[]' ELSE issues END
                WHERE order_id=?
                """,
                (to_status, utc_now(), resolved, resolved, order_id),
            )
            db.execute(
                """
                INSERT INTO events (
                    created_at, order_id, event_type, from_status, to_status, details,
                    minutes_saved, revenue_protected_egp, recovered_revenue_egp,
                    avoided_cost_egp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    utc_now(),
                    order_id,
                    event_type,
                    order["status"],
                    to_status,
                    json.dumps(details or {}, ensure_ascii=False),
                    minutes_saved,
                    revenue_protected,
                    recovered_revenue,
                    avoided_cost,
                ),
            )
        return self.get_order(order_id)

    def update_address(self, order_id: str, address: str, landmark: str) -> dict[str, Any]:
        if not address_is_complete(address):
            raise ValueError("Address must contain a building number and at least 12 characters")
        with self.session() as db:
            db.execute(
                "UPDATE orders SET address=?, landmark=?, issues='[]', risk_score=15, updated_at=? WHERE order_id=?",
                (address.strip(), landmark.strip(), utc_now(), order_id),
            )
        return self._transition(
            order_id,
            "needs_confirmation",
            "address_corrected",
            {"address": address, "landmark": landmark},
            minutes_saved=6,
        )

    def confirm(self, order_id: str) -> dict[str, Any]:
        order = self.get_order(order_id)
        if order["status"] not in {"needs_confirmation", "address_needed"}:
            raise ValueError(f"Cannot confirm an order with status {order['status']}")
        if not address_is_complete(order["address"]):
            raise ValueError("Complete the address before confirming the order")
        return self._transition(
            order_id,
            "confirmed",
            "customer_confirmed",
            minutes_saved=4,
            revenue_protected=float(order["amount_egp"]),
        )

    def fail_delivery(self, order_id: str, reason: str) -> dict[str, Any]:
        return self._transition(
            order_id,
            "failed_delivery",
            "delivery_failed",
            {"reason": reason},
        )

    def reschedule(self, order_id: str, date: str, window: str) -> dict[str, Any]:
        order = self.get_order(order_id)
        if order["status"] != "failed_delivery":
            raise ValueError("Only a failed delivery can be rescheduled")
        try:
            datetime.strptime(date, "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError("Date must use YYYY-MM-DD") from exc
        with self.session() as db:
            db.execute(
                "UPDATE orders SET preferred_date=?, preferred_window=?, updated_at=? WHERE order_id=?",
                (date, window.strip(), utc_now(), order_id),
            )
        return self._transition(
            order_id,
            "rescheduled",
            "delivery_rescheduled",
            {"date": date, "window": window},
            minutes_saved=8,
            recovered_revenue=float(order["amount_egp"]),
            avoided_cost=float(order["shipping_cost_egp"]),
        )

    def cancel(self, order_id: str, reason: str) -> dict[str, Any]:
        return self._transition(order_id, "cancelled", "order_cancelled", {"reason": reason}, minutes_saved=3)

    def deliver(self, order_id: str) -> dict[str, Any]:
        order = self.get_order(order_id)
        if order["status"] not in {"confirmed", "rescheduled"}:
            raise ValueError("Only confirmed or rescheduled orders can be delivered")
        return self._transition(order_id, "delivered", "order_delivered")

    def list_orders(self, status: str | None = None) -> list[dict[str, Any]]:
        orders = self._rows()
        if status:
            orders = [order for order in orders if order["status"] == status]
        return sorted(orders, key=lambda order: (-int(order["risk_score"]), order["order_id"]))

    def metrics(self) -> dict[str, Any]:
        with self.session() as db:
            order_counts = {
                row["status"]: row["count"]
                for row in db.execute("SELECT status, COUNT(*) AS count FROM orders GROUP BY status")
            }
            totals = db.execute(
                """
                SELECT
                    COALESCE(SUM(minutes_saved), 0) AS minutes_saved,
                    COALESCE(SUM(revenue_protected_egp), 0) AS revenue_protected,
                    COALESCE(SUM(recovered_revenue_egp), 0) AS recovered_revenue,
                    COALESCE(SUM(avoided_cost_egp), 0) AS avoided_cost,
                    COUNT(*) AS actions
                FROM events
                """
            ).fetchone()
            total_orders = db.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        return {
            "total_orders": total_orders,
            "orders_by_status": order_counts,
            "agent_actions": int(totals["actions"]),
            "minutes_saved": round(float(totals["minutes_saved"]), 1),
            "hours_saved": round(float(totals["minutes_saved"]) / 60, 2),
            "revenue_protected_egp": round(float(totals["revenue_protected"]), 2),
            "recovered_revenue_egp": round(float(totals["recovered_revenue"]), 2),
            "avoided_cost_egp": round(float(totals["avoided_cost"]), 2),
        }

    def audit_log(self) -> list[dict[str, Any]]:
        with self.session() as db:
            rows = db.execute("SELECT * FROM events ORDER BY id DESC").fetchall()
        events = []
        for row in rows:
            event = dict(row)
            event["details"] = json.loads(event["details"] or "{}")
            events.append(event)
        return events

    def generate_dashboard(self, output_path: Path | str = DEFAULT_DASHBOARD) -> Path:
        output = Path(output_path)
        metrics = self.metrics()
        orders = self.list_orders()
        events = self.audit_log()

        cards = [
            ("Revenue protected", f"EGP {metrics['revenue_protected_egp']:,.0f}"),
            ("Revenue recovered", f"EGP {metrics['recovered_revenue_egp']:,.0f}"),
            ("Delivery cost avoided", f"EGP {metrics['avoided_cost_egp']:,.0f}"),
            ("Staff time saved", f"{metrics['minutes_saved']:,.0f} min"),
        ]
        card_html = "".join(
            f'<article class="card"><span>{html.escape(label)}</span><strong>{html.escape(value)}</strong></article>'
            for label, value in cards
        )
        order_rows = "".join(
            "<tr>"
            f"<td>{html.escape(order['order_id'])}</td>"
            f"<td>{html.escape(order['customer_name'])}</td>"
            f"<td>EGP {float(order['amount_egp']):,.0f}</td>"
            f"<td><span class='status'>{html.escape(order['status'].replace('_', ' '))}</span></td>"
            f"<td>{order['risk_score']}</td>"
            f"<td>{html.escape(', '.join(order['issues']) or '—')}</td>"
            "</tr>"
            for order in orders
        )
        event_rows = "".join(
            "<tr>"
            f"<td>{html.escape(event['created_at'])}</td>"
            f"<td>{html.escape(event['order_id'])}</td>"
            f"<td>{html.escape(event['event_type'].replace('_', ' '))}</td>"
            f"<td>{html.escape((event['from_status'] or '—') + ' → ' + (event['to_status'] or '—'))}</td>"
            "</tr>"
            for event in events[:12]
        ) or "<tr><td colspan='4'>No agent actions yet. Run the demo commands.</td></tr>"

        document = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Wasel Impact Dashboard</title>
  <style>
    :root {{ --ink:#17201c; --muted:#637069; --green:#126b4a; --lime:#d9f46c; --cream:#f5f3e9; --line:#d9ddd7; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; font:15px/1.5 Inter,Segoe UI,sans-serif; background:var(--cream); color:var(--ink); }}
    main {{ width:min(1160px,calc(100% - 32px)); margin:40px auto; }}
    header {{ display:flex; justify-content:space-between; gap:24px; align-items:end; margin-bottom:24px; }}
    h1 {{ font-size:42px; letter-spacing:-1.5px; margin:0; }}
    .eyebrow {{ color:var(--green); font-weight:800; text-transform:uppercase; letter-spacing:1px; }}
    .cards {{ display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin:24px 0; }}
    .card {{ background:white; border:1px solid var(--line); border-radius:16px; padding:20px; }}
    .card span {{ display:block; color:var(--muted); }}
    .card strong {{ display:block; font-size:27px; margin-top:8px; }}
    section {{ background:white; border:1px solid var(--line); border-radius:16px; padding:20px; margin-top:16px; overflow:auto; }}
    h2 {{ margin:0 0 14px; font-size:20px; }}
    table {{ width:100%; border-collapse:collapse; white-space:nowrap; }}
    th,td {{ text-align:left; padding:11px 10px; border-bottom:1px solid #edf0ec; }}
    th {{ color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.5px; }}
    .status {{ background:var(--lime); border-radius:999px; padding:4px 9px; font-weight:700; }}
    .note {{ color:var(--muted); max-width:600px; }}
    @media (max-width:800px) {{ .cards {{ grid-template-columns:1fr 1fr; }} header {{ display:block; }} }}
  </style>
</head>
<body><main>
  <header><div><div class="eyebrow">Wasel · COD operations agent</div><h1>Impact dashboard</h1></div><p class="note">Generated from the agent's append-only audit log. Values represent the included demo dataset, not a production claim.</p></header>
  <div class="cards">{card_html}</div>
  <section><h2>Order queue</h2><table><thead><tr><th>Order</th><th>Customer</th><th>Value</th><th>Status</th><th>Risk</th><th>Issues</th></tr></thead><tbody>{order_rows}</tbody></table></section>
  <section><h2>Recent agent actions</h2><table><thead><tr><th>Time</th><th>Order</th><th>Action</th><th>Transition</th></tr></thead><tbody>{event_rows}</tbody></table></section>
</main></body></html>"""
        output.write_text(document, encoding="utf-8")
        return output.resolve()
