from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column as col, relationship

from .db import Base
from .expansion_models import ShiftSupport
from .models import PickupBatch, utcnow


class HandoffAudit(Base):
    __tablename__ = 'handoff_audits'
    __table_args__ = (
        CheckConstraint('scan_count > 0 AND late_count BETWEEN 0 AND scan_count'),
        CheckConstraint('sla_minutes BETWEEN 15 AND 180 AND worst_minutes BETWEEN 0 AND 1440'),
    )
    id: Mapped[int] = col(primary_key=True)
    support_id: Mapped[int] = col(ForeignKey('shift_supports.id'), unique=True)
    batch_code: Mapped[str] = col(ForeignKey('pickup_batches.code'))
    scan_count: Mapped[int]
    late_count: Mapped[int]
    worst_minutes: Mapped[int]
    sla_minutes: Mapped[int]
    verdict: Mapped[str] = col(Enum('insufficient', 'breach', 'clear'))
    created_by: Mapped[str] = col(ForeignKey('users.username'))
    created_at: Mapped[datetime] = col(DateTime, default=utcnow)
    support: Mapped[ShiftSupport] = relationship()
    batch: Mapped[PickupBatch] = relationship()


class RecoveryDispatch(Base):
    __tablename__ = 'recovery_dispatches'
    __table_args__ = (CheckConstraint('headcount BETWEEN 1 AND 6'),)
    id: Mapped[int] = col(primary_key=True)
    audit_id: Mapped[int] = col(ForeignKey('handoff_audits.id'), unique=True)
    business_date: Mapped[date] = col(Date)
    headcount: Mapped[int]
    plan_note: Mapped[str] = col(String(400))
    status: Mapped[str] = col(Enum('proposed', 'released', 'replan', 'verified'), default='proposed')
    evidence: Mapped[HandoffAudit] = relationship()


class RecoveryCheck(Base):
    __tablename__ = 'recovery_checks'
    __table_args__ = (
        CheckConstraint('scan_count > 0 AND late_count BETWEEN 0 AND scan_count'),
        CheckConstraint('worst_minutes BETWEEN 0 AND 1440'),
    )
    id: Mapped[int] = col(primary_key=True)
    dispatch_id: Mapped[int] = col(ForeignKey('recovery_dispatches.id'), index=True)
    batch_code: Mapped[str] = col(ForeignKey('pickup_batches.code'), unique=True)
    scan_count: Mapped[int]
    late_count: Mapped[int]
    worst_minutes: Mapped[int]
    verdict: Mapped[str] = col(Enum('insufficient', 'breach', 'clear'))
    checked_by: Mapped[str] = col(ForeignKey('users.username'))
    created_at: Mapped[datetime] = col(DateTime, default=utcnow)
    batch: Mapped[PickupBatch] = relationship()
