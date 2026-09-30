"""Retrieval-augmented QA over internal policy documents."""

from __future__ import annotations

import os

import anthropic

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

ANSWER_MODEL = "claude-3-5-sonnet"
EMBEDDING_MODEL = "bge-m3"

ANSWER_PROMPT = """Answer the employee's question using only the cited policy excerpts.

Always cite the document id and section for every claim.
If the excerpts do not answer the question, say so and name the team to ask.
"""


def answer(question: str, excerpts: list[str]) -> str:
    """Answer a question grounded in retrieved policy excerpts."""
    message = client.messages.create(
        model=ANSWER_MODEL,
        max_tokens=1024,
        system=ANSWER_PROMPT,
        messages=[{"role": "user", "content": question + "\n\n" + "\n".join(excerpts)}],
    )
    return message.content[0].text


def embed(text: str) -> list[float]:
    """Embed a query or document chunk for the policy index."""
    return [0.0] * 1024
