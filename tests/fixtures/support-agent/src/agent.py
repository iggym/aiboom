"""Support agent — deliberately contains a realistic AI surface.

This fixture is scanned by the bundled scanner in tests, so it exercises:
  * an OpenAI client and a floating alias plus a pinned snapshot
  * an embedding model
  * a prompt file and an inline triple-quoted prompt
  * a read-only tool and a high-risk financial tool
  * an MCP server started over stdio
"""

from __future__ import annotations

import os

from openai import OpenAI

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

MODEL = "gpt-4.1"
ESCALATION_MODEL = "gpt-4.1-2024-08-06"
EMBEDDING_MODEL = "text-embedding-3-small"

TRIAGE_PROMPT = """You triage inbound support tickets.

Classify the ticket into one of: billing, bug, how-to, cancellation.
Return JSON with the fields `category` and `urgency`.
"""


def draft_reply(ticket_id: str, context: str) -> str:
    """Draft a reply for a support ticket using retrieval context."""
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": TRIAGE_PROMPT},
            {"role": "user", "content": context},
        ],
    )
    return response.choices[0].message.content or ""


def summarise_thread(ticket_id: str, messages: list[str]) -> str:
    """Summarise a long ticket thread into a short handover note."""
    response = client.chat.completions.create(
        model=ESCALATION_MODEL,
        messages=[{"role": "user", "content": "\n".join(messages)}],
    )
    return response.choices[0].message.content or ""


def embed(text: str) -> list[float]:
    """Embed text for the help-centre index."""
    response = client.embeddings.create(model=EMBEDDING_MODEL, input=text)
    return response.data[0].embedding
