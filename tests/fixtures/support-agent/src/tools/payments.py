"""Tool definitions for the support agent."""

from __future__ import annotations

import json
import subprocess
from typing import Any


def issue_refund(order_id: str, amount_cents: int, reason: str) -> dict[str, Any]:
    """Issue a refund for an order via the payments API."""
    return {"order_id": order_id, "refunded_cents": amount_cents, "reason": reason}


def lookup_ticket(ticket_id: str) -> dict[str, Any]:
    """Read a support ticket from the ticketing system."""
    return {"ticket_id": ticket_id}


def delete_customer_account(customer_id: str) -> None:
    """Delete a customer account and all associated data."""
    subprocess.run(["rm", "-rf", f"/data/customers/{customer_id}"], check=False)


def send_email(to: str, subject: str, body: str) -> None:
    """Send an email to a customer."""
    print(json.dumps({"to": to, "subject": subject, "body": body}))
