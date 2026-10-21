"""Structured answers the model must return, validated before anything is used or shown.

The model returns JSON only; anything that does not fit these models is rejected (AiInvalid) and the
caller changes no score. Lengths are capped so output cannot flood a page.
"""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

Short = Field(max_length=300)
Long = Field(max_length=1200)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SentenceError(_Strict):
    wrong: str = Short  # the faulty fragment, as written
    right: str = Short
    kind: str = Field(max_length=60)  # e.g. "Artikel", "Kasus"


class WordResult(_Strict):
    word: str = Field(max_length=80)
    ok: bool
    note: str = Short


class SentenceCheck(_Strict):
    errors: list[SentenceError] = Field(max_length=20)
    word_results: list[WordResult] = Field(max_length=20)
    rule: str = Short
    natural: str = Short
    corrected: str = Short


class Explanation(_Strict):
    rule: str = Short
    explanation: str = Long
    merke: str = Short
    explanation_uk: str = Long


class Task(_Strict):
    prompt: str = Short
    word: str = Field(max_length=80)
    translation_uk: str = Short
    translation_en: str = Short


class TaskSet(_Strict):
    tasks: list[Task] = Field(min_length=1, max_length=10)


class AnswerGrade(_Strict):
    verdict: Literal["richtig", "teilweise", "falsch"]
    comment: str = Short


class AiInvalid(ValueError):
    """The model's reply is not valid structured output."""


def parse(model: type[_Strict], text: str) -> _Strict:
    """Parse a model reply; accepts one JSON object, optionally wrapped in a ``` fence."""
    body = text.strip()
    if body.startswith("```"):
        body = body.strip("`")
        body = body.removeprefix("json").strip()
    try:
        return model.model_validate(json.loads(body))
    except (json.JSONDecodeError, ValidationError) as e:
        raise AiInvalid(f"invalid {model.__name__}: {type(e).__name__}") from None  # no model text in the message
