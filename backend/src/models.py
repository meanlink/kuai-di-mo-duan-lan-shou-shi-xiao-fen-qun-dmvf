from datetime import UTC, datetime

from sqlalchemy import (
    JSON, CheckConstraint, Date, DateTime, Enum, ForeignKey, Integer, String,
    Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column as col, relationship

from .db import Base


def utcnow():
    return datetime.now(UTC).replace(tzinfo=None)


class User(Base):
    __tablename__ = 'users'
    username: Mapped[str] = col(String(32), primary_key=True)
    role: Mapped[str] = col(Enum('admin', 'analyst', 'viewer'))
    password_hash: Mapped[str] = col(String(200))


class Station(Base):
    __tablename__ = 'stations'
    __table_args__ = (CheckConstraint('sla_minutes BETWEEN 15 AND 180'),)
    code: Mapped[str] = col(String(16), primary_key=True)
    name: Mapped[str] = col(String(64), unique=True)
    region: Mapped[str] = col(String(32), index=True)
    lead: Mapped[str] = col(String(40))
    route_type: Mapped[str] = col(String(32))
    sla_minutes: Mapped[int] = col(Integer)


class PickupBatch(Base):
    __tablename__ = 'pickup_batches'
    code: Mapped[str] = col(String(32), primary_key=True)
    station_code: Mapped[str] = col(ForeignKey('stations.code'), index=True)
    business_date = col(Date, nullable=False, index=True)
    shift: Mapped[str] = col(Enum('morning', 'afternoon', 'evening'))
    source_name: Mapped[str] = col(String(120))
    recorded_by: Mapped[str] = col(ForeignKey('users.username'))
    created_at = col(DateTime, nullable=False, default=utcnow)
    station: Mapped[Station] = relationship()
    scans: Mapped[list['PickupScan']] = relationship(cascade='all, delete-orphan')


class PickupScan(Base):
    __tablename__ = 'pickup_scans'
    __table_args__ = (
        CheckConstraint('elapsed_minutes BETWEEN 0 AND 1440'),
        CheckConstraint('scanned_at >= planned_at'),
    )
    parcel_code: Mapped[str] = col(String(36), primary_key=True)
    batch_code: Mapped[str] = col(ForeignKey('pickup_batches.code'), index=True)
    planned_at = col(DateTime, nullable=False)
    scanned_at = col(DateTime, nullable=False)
    elapsed_minutes: Mapped[int] = col(Integer)


class ClusterRun(Base):
    __tablename__ = 'cluster_runs'
    __table_args__ = (CheckConstraint('k BETWEEN 2 AND 5'),)
    id: Mapped[int] = col(primary_key=True)
    start_date = col(Date, nullable=False)
    end_date = col(Date, nullable=False)
    k: Mapped[int] = col(Integer)
    min_samples: Mapped[int] = col(Integer)
    fingerprint: Mapped[str] = col(String(64), unique=True)
    snapshot: Mapped[list] = col(JSON)
    state: Mapped[str] = col(Enum('queued', 'review', 'approved', 'failed'), default='queued', index=True)
    result: Mapped[dict | None] = col(JSON, nullable=True)
    error: Mapped[str | None] = col(String(240))
    created_by: Mapped[str] = col(ForeignKey('users.username'))
    reviewed_by: Mapped[str | None] = col(ForeignKey('users.username'))
    created_at = col(DateTime, nullable=False, default=utcnow)
    reviewed_at = col(DateTime)


class RemediationTask(Base):
    __tablename__ = 'remediation_tasks'
    __table_args__ = (UniqueConstraint('run_id', 'station_code'),)
    id: Mapped[int] = col(primary_key=True)
    run_id: Mapped[int] = col(ForeignKey('cluster_runs.id'))
    station_code: Mapped[str] = col(ForeignKey('stations.code'), index=True)
    segment: Mapped[int] = col(Integer)
    source: Mapped[str] = col(Enum('cluster', 'manual'))
    status: Mapped[str] = col(Enum('open', 'doing', 'resolved', 'closed'), default='open', index=True)
    action: Mapped[str] = col(String(160))
    review_note: Mapped[str | None] = col(Text)
    evidence: Mapped[str | None] = col(Text)
    due_date = col(Date, nullable=False)
    created_at = col(DateTime, nullable=False, default=utcnow)
    station: Mapped[Station] = relationship()


class AuditEvent(Base):
    __tablename__ = 'audit_events'
    id: Mapped[int] = col(primary_key=True)
    actor: Mapped[str] = col(String(32))
    action: Mapped[str] = col(String(40))
    subject: Mapped[str] = col(String(64), index=True)
    detail: Mapped[dict] = col(JSON)
    created_at = col(DateTime, nullable=False, default=utcnow)


def audit(db, actor, action, subject, **detail):
    db.add(AuditEvent(actor=actor, action=action, subject=str(subject), detail=detail))
