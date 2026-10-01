---
name: wasel
description: Operate Wasel, an Arabic-first cash-on-delivery confirmation and failed-delivery recovery workflow for small ecommerce stores. Use for scanning orders, correcting addresses, confirming COD orders, rescheduling failed deliveries, and reporting business impact.
version: 0.1.0
author: Mohamed ElDeeb & CODEX (Wasel Hackathon Team)
license: MIT
platforms: [windows, macos, linux]
metadata:
  hermes:
    tags: [ecommerce, cod, egypt, operations, telegram]
    category: productivity
    requires_toolsets: [terminal]
---

# Wasel COD Operations

Use the terminal tool to run Wasel from the repository root. The repository root is three directories above `${HERMES_SKILL_DIR}`. Set the terminal working directory to that root, then run commands as `python3 wasel.py --json <command>`.

## Modes

Determine whether the user is acting as a store operator or as a demo customer.

- Operator requests include scanning the queue, reviewing risks, viewing metrics, or marking a delivery failure.
- A customer flow begins only when the user gives a specific order ID and asks to confirm, correct, cancel, or reschedule it.
- In ambiguous cases, ask whether the user is the operator or the customer before changing state.

## Operator workflow

1. Initialize a fresh demo only when explicitly asked: `python3 wasel.py --json reset`.
2. Scan orders: `python3 wasel.py --json scan`.
3. Summarize the highest-risk orders first. Never describe every row unless asked.
4. For one order, retrieve its safe next step: `python3 wasel.py --json plan ORDER_ID`.
5. Use a mutation command only after the user supplies or explicitly approves the relevant information.
6. After mutations, show metrics with `python3 wasel.py --json metrics`.
7. Generate the visual report with `python3 wasel.py --json dashboard` when asked.

## Customer workflow

1. Require the order ID. Retrieve `python3 wasel.py --json plan ORDER_ID`.
2. Do not reveal the stored address, phone number, or other personal details. You may state the order ID and total.
3. Send the `suggested_message` in the customer's language, adapting tone without changing facts.
4. If the address is incomplete, collect building number, street, area, and landmark. Read the proposed normalized address back and get explicit confirmation before running:

   `python3 wasel.py --json update-address ORDER_ID --address "FULL ADDRESS" --landmark "LANDMARK"`

5. After a valid address, ask the customer to confirm the order total and availability. On an explicit yes, run:

   `python3 wasel.py --json confirm ORDER_ID`

6. For `failed_delivery`, collect a date in YYYY-MM-DD and a time window, repeat them back, get explicit confirmation, then run:

   `python3 wasel.py --json reschedule ORDER_ID --date YYYY-MM-DD --window "TIME WINDOW"`

7. For cancellation, ask for a reason and one explicit confirmation, then run:

   `python3 wasel.py --json cancel ORDER_ID --reason "REASON"`

## Operator mutation commands

- Record a failed delivery only with a supplied reason:
  `python3 wasel.py --json fail-delivery ORDER_ID --reason "REASON"`
- Mark delivered only after operator confirmation:
  `python3 wasel.py --json deliver ORDER_ID`

## Safety rules

- Never invent an order, address, date, customer reply, status, or impact value.
- Never mark an order confirmed based on an ambiguous response.
- Never modify item, price, discount, payment method, or shipping fee.
- Never contact possible duplicates until an operator reviews them.
- Do not expose one customer's information to another user.
- Treat command errors as blocking; explain the error and do not claim the update succeeded.
- Monetary figures are measured from the included demonstration data unless the operator has imported real data.

## Verification

After every state change, retrieve the order again with `python3 wasel.py --json order ORDER_ID` and report its exact new status. For a complete demo, confirm that `python3 wasel.py --json metrics` and `python3 wasel.py --json dashboard` succeed.
