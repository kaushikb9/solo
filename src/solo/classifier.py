"""Classifier — turns a raw entry into (kind, summary, priority).

All LLM calls go through solo.llm.LLMClient. classify_pending never raises;
failures bump classification_attempts and are picked up by the next call
until max_attempts is reached.
"""

import logging
import sqlite3
from typing import Literal, Protocol

from pydantic import BaseModel, Field

from solo import db

logger = logging.getLogger(__name__)


class ClassifyResult(BaseModel):
    kind: Literal["idea", "soft_task", "hard_task", "note"]
    summary: str = Field(min_length=1, max_length=200)
    priority: Literal["low", "medium", "high"]


class _SupportsStructured(Protocol):
    async def structured(self, prompt_name, schema, *, model, vars): ...


async def classify_pending(
    conn: sqlite3.Connection,
    llm: _SupportsStructured,
    *,
    model: str,
    limit: int = 50,
    max_attempts: int = 3,
) -> int:
    """Classify pending entries. Sequential. Idempotent. Never raises.

    Returns the number of rows successfully classified in this call.
    """
    rows = db.fetch_unclassified(conn, limit=limit, max_attempts=max_attempts)
    success = 0
    for row in rows:
        try:
            result = await llm.structured(
                "classifier",
                ClassifyResult,
                model=model,
                vars={"entry_text": row["raw_text"]},
            )
        except Exception as exc:
            logger.warning("classify failed for entry %s: %s", row["id"], exc)
            db.record_classification_failure(conn, row["id"])
            continue
        wrote = db.apply_classification(
            conn, row["id"], result.kind, result.summary, result.priority
        )
        if wrote:
            success += 1
    return success
