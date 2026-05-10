"""Classifier — turns a raw entry into (kind, summary, priority).

All LLM calls go through solo.llm.LLMClient. classify_pending never raises;
failures bump classification_attempts and are picked up by the next call
until max_attempts is reached.
"""

from typing import Literal

from pydantic import BaseModel


class ClassifyResult(BaseModel):
    kind: Literal["idea", "soft_task", "hard_task", "note"]
    summary: str
    priority: Literal["low", "medium", "high"]
