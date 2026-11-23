from datetime import date, datetime

from sqlalchemy import JSON, CheckConstraint, Date, DateTime, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column as col, relationship

from .db import Base
from .models import RemediationTask, utcnow


class ShiftFollowup(Base):
    __tablename__ = 'shift_followups'
    __table_args__ = (
        CheckConstraint('end_date >= start_date'),
        CheckConstraint('baseline_count >= 12 AND baseline_late BETWEEN 0 AND baseline_count'),
        CheckConstraint('sla_minutes BETWEEN 15 AND 180'),
        CheckConstraint("(status = 'scheduled' AND measured_count IS NULL AND measured_late IS NULL) OR "
                        "(status <> 'scheduled' AND measured_count IS NOT NULL AND measured_count >= 12 "
                        "AND measured_late IS NOT NULL AND measured_late BETWEEN 0 AND measured_count)"),
    )
    id: Mapped[int] = col(primary_key=True)
    task_id: Mapped[int] = col(ForeignKey('remediation_tasks.id'), unique=True)
    shift: Mapped[str] = col(Enum('morning', 'afternoon', 'evening'))
    start_date: Mapped[date] = col(Date)
    end_date: Mapped[date] = col(Date)
    sla_minutes: Mapped[int]
    baseline_count: Mapped[int]
    baseline_late: Mapped[int]
    baseline_batches: Mapped[list[str]] = col(JSON)
    measured_count: Mapped[int | None]
    measured_late: Mapped[int | None]
    measured_batches: Mapped[list[str] | None] = col(JSON(none_as_null=True))
    status: Mapped[str] = col(Enum('scheduled', 'measured', 'passed', 'failed'), default='scheduled')
    review_note: Mapped[str | None] = col(String(400))
    created_at: Mapped[datetime] = col(DateTime, default=utcnow)
    task: Mapped[RemediationTask] = relationship()


class ShiftSupport(Base):
    __tablename__ = 'shift_supports'
    __table_args__ = (
        CheckConstraint('headcount BETWEEN 1 AND 6'),
        CheckConstraint("(status = 'completed' AND actual_headcount IS NOT NULL "
                        "AND actual_headcount BETWEEN 1 AND headcount AND evidence_batch IS NOT NULL) OR "
                        "(status <> 'completed' AND actual_headcount IS NULL AND evidence_batch IS NULL)"),
    )
    id: Mapped[int] = col(primary_key=True)
    followup_id: Mapped[int] = col(ForeignKey('shift_followups.id'), unique=True)
    business_date: Mapped[date] = col(Date)
    headcount: Mapped[int]
    request_note: Mapped[str] = col(String(400))
    status: Mapped[str] = col(Enum('requested', 'approved', 'returned', 'completed'), default='requested')
    decision_note: Mapped[str | None] = col(String(400))
    actual_headcount: Mapped[int | None]
    evidence_batch: Mapped[str | None] = col(ForeignKey('pickup_batches.code'), unique=True)
    completion_note: Mapped[str | None] = col(String(400))
    created_at: Mapped[datetime] = col(DateTime, default=utcnow)
    followup: Mapped[ShiftFollowup] = relationship()
