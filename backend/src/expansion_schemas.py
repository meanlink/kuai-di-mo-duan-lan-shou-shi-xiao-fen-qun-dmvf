from datetime import date
from typing import Literal

from pydantic import Field

from .schemas import Input, Shift, Window


class FollowupPlan(Window):
    task_id: int = Field(gt=0)
    shift: Shift


class ReviewNote(Input):
    note: str = Field(min_length=12, max_length=400)


class SupportPlan(Input):
    business_date: date
    headcount: int = Field(ge=1, le=6)
    note: str = Field(min_length=12, max_length=400)


class SupportRequest(SupportPlan):
    followup_id: int = Field(gt=0)


class SupportDecision(ReviewNote):
    decision: Literal['approved', 'returned']


class SupportCompletion(ReviewNote):
    actual_headcount: int = Field(ge=1, le=6)
    evidence_batch: str = Field(min_length=1, max_length=32)
