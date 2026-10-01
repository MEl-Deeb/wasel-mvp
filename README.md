# Wasel

Wasel is an Arabic-first COD operations agent for small Egyptian ecommerce stores. It detects risky orders, collects missing delivery details, confirms orders, and recovers failed deliveries while maintaining a measurable audit trail.

This repository contains the Day 1 and Day 2 hackathon MVP:

- CSV ingestion and ten-order demo dataset
- Address, phone, duplicate, high-value, and failed-delivery checks
- Risk-ranked order queue and explicit state transitions
- Egyptian Arabic and English confirmation prompts
- Address correction, confirmation, cancellation, and rescheduling
- Revenue-protected, revenue-recovered, avoided-cost, and time-saved metrics
- Standalone HTML impact dashboard
- Project-local Hermes skill for CLI and Telegram operation
- Automated tests using only Python's standard library

## Architecture

```text
Telegram user
     │
Hermes messaging gateway
     │
Wasel project skill (.agents/skills/wasel/SKILL.md)
     │ terminal commands
Python CLI ── SQLite state + audit log ── HTML impact dashboard
     │
Orders CSV
```

Business rules and financial calculations are deterministic Python. Hermes handles conversation, language, next-step reasoning, and tool orchestration.

## Requirements

- Python 3.10 or newer
- Hermes Agent for the agent and Telegram experience
- No Python packages are required

## Run the local MVP in under five minutes

From this directory:

```bash
python3 wasel.py reset
python3 wasel.py scan
python3 wasel.py list
python3 wasel.py plan WSL-1002
```

Complete an address and confirm the order:

```bash
python3 wasel.py update-address WSL-1002 --address "14 Makram Ebeid St, Nasr City" --landmark "City Centre"
python3 wasel.py confirm WSL-1002
```

Recover a failed delivery:

```bash
python3 wasel.py plan WSL-1006
python3 wasel.py reschedule WSL-1006 --date 2026-10-02 --window "18:00-21:00"
```

Generate measurable results:

```bash
python3 wasel.py metrics
python3 wasel.py dashboard
xdg-open ./dashboard.html
```

Use `--json` before the command for agent-friendly output, for example:

```bash
python3 wasel.py --json scan
```

Reset at any time with `python3 wasel.py reset`.

## Use Wasel with Hermes

Wasel includes a project-local Hermes skill. Project skills require a Git repository and are trust-gated. When using the ZIP archive, run these commands from this directory:

```bash
git init
hermes skills trust
hermes chat --toolsets skills,terminal
```

Inside Hermes, try:

```text
/wasel Reset the demo, scan the order queue, and show the three highest-risk orders.
```

Then test a customer flow:

```text
/wasel I am the customer for WSL-1002 and want to confirm my order.
```

For a failed-delivery flow:

```text
/wasel I am the customer for WSL-1006 and want delivery on 2026-10-02 between 6 and 9 PM.
```

Hermes should request explicit confirmation before changing any state.

## Connect Hermes to Telegram

Do not commit Telegram credentials to this repository.

1. Create a bot through `@BotFather` in Telegram.
2. Find your numeric Telegram user ID through `@userinfobot`.
3. Run the official setup wizard:

   ```bash
   hermes gateway setup
   ```

4. Select Telegram, enter the bot token, and allowlist your numeric user ID.
5. Start in the foreground so errors remain visible:

   ```bash
   hermes gateway
   ```

6. Message the bot:

   ```text
   /wasel Reset the demo and scan today's orders.
   ```

For a two-person demo, allowlist both Telegram user IDs in the gateway setup. One person can act as the store operator and the other as the customer. Never enable unrestricted users for a public deployment.

## Import your own orders

Copy `data/sample_orders.csv`, keep its header, replace the rows, then run:

```bash
python3 wasel.py import /path/to/orders.csv
python3 wasel.py scan
```

The accepted statuses are `new`, `needs_confirmation`, `address_needed`, `needs_review`, `confirmed`, `failed_delivery`, `rescheduled`, `cancelled`, and `delivered`.

## Run tests

```bash
python3 -m unittest discover -s tests -v
```

## Three-minute demo sequence

1. Ask Hermes in Telegram to reset and scan the queue.
2. Show that WSL-1002 needs an address and WSL-1004 is a possible duplicate.
3. Act as the WSL-1002 customer, provide the complete address, and confirm.
4. Reschedule failed order WSL-1006.
5. Ask Hermes for impact metrics and generate the dashboard.

The supplied financial results are demonstration measurements from the included dataset. A real pilot should replace them with actual store orders and measured handling times.

## Safety boundaries

- Customer confirmation is required before order-state changes.
- Duplicate orders are held for operator review.
- Hermes cannot change prices, discounts, payment methods, or shipping fees.
- Credentials remain in Hermes configuration, not the project.
- Every mutation is recorded in an append-only event log.
