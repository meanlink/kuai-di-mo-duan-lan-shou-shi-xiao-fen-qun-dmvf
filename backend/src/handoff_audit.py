from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from .expansion import load, support_record
from .expansion_models import ShiftFollowup, ShiftSupport
from .handoff_metrics import measure_batch, metrics_record
from .handoff_models import HandoffAudit, RecoveryDispatch
from .models import PickupBatch, RemediationTask


def audit_record(row):
    batch = row.batch
    return metrics_record(row, row.sla_minutes) | {
        'id': row.id, 'support_id': row.support_id, 'created_by': row.created_by,
        'created_at': row.created_at, 'business_date': batch.business_date, 'shift': batch.shift,
        'station_code': batch.station_code, 'station_name': batch.station.name,
        'task_id': row.support.followup.task_id, 'followup_id': row.support.followup_id,
        'source_name': batch.source_name,
    }


def audit_detail(db, row):
    dispatch_id = db.scalar(select(RecoveryDispatch.id).where(RecoveryDispatch.audit_id == row.id))
    return audit_record(row) | {'dispatch_id': dispatch_id}


def ledger(db):
    audits = select(HandoffAudit).options(
        joinedload(HandoffAudit.batch).joinedload(PickupBatch.station),
        joinedload(HandoffAudit.support).joinedload(ShiftSupport.followup),
    ).order_by(HandoffAudit.id.desc())
    pending = select(ShiftSupport).options(
        joinedload(ShiftSupport.followup).joinedload(ShiftFollowup.task).joinedload(RemediationTask.station),
    ).where(
        ShiftSupport.status == 'completed',
        ~select(HandoffAudit.id).where(HandoffAudit.support_id == ShiftSupport.id).exists(),
    ).order_by(ShiftSupport.id.desc())
    return {'audits': [audit_record(row) for row in db.scalars(audits)],
            'pending': [support_record(row) for row in db.scalars(pending)]}


def inspect_handoff(db, key, actor):
    support = load(db, ShiftSupport, key, '支援单', lock=True)
    if support.status != 'completed':
        raise HTTPException(409, '支援核销后才能核查交接扫描证据')
    if db.scalar(select(HandoffAudit.id).where(HandoffAudit.support_id == key)):
        raise HTTPException(409, '该支援单已冻结交接证据')
    sla = support.followup.sla_minutes
    row = HandoffAudit(support_id=key, batch_code=support.evidence_batch, sla_minutes=sla, created_by=actor,
                       **measure_batch(db, support.evidence_batch, sla))
    db.add(row)
    db.commit()
    db.refresh(row)
    return audit_detail(db, row)
