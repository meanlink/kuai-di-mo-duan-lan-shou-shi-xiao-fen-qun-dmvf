from datetime import date
from enum import StrEnum

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field


class Input(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')


class Shift(StrEnum):
    morning = 'morning'
    afternoon = 'afternoon'
    evening = 'evening'


class TaskStatus(StrEnum):
    open = 'open'
    doing = 'doing'
    resolved = 'resolved'
    closed = 'closed'


class Login(Input):
    username: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=1, max_length=128)


class Window(Input):
    start: date
    end: date


def validate_window(window):
    if not 0 <= (window.end - window.start).days <= 30:
        raise HTTPException(422, '统计窗须为 1–31 天，结束日期不得早于开始日期')
    return window


class ImportBatch(Input):
    code: str = Field(pattern=r'^[A-Z0-9][A-Z0-9-]{3,31}$')
    station_code: str = Field(pattern=r'^[A-Z0-9-]{3,16}$')
    business_date: date
    shift: Shift
    source_name: str = Field(min_length=5, max_length=120, pattern=r'^[^/\\]+\.csv$')
    csv: str = Field(min_length=1, max_length=160000)


class RunRequest(Window):
    k: int = Field(default=3, ge=2, le=5)
    min_samples: int = Field(default=24, ge=12, le=500)


class ManualReview(Input):
    segment: int = Field(ge=1, le=5)
    note: str = Field(min_length=12, max_length=400)


class AdvanceTask(Input):
    status: TaskStatus
    evidence: str | None = Field(default=None, max_length=600)
