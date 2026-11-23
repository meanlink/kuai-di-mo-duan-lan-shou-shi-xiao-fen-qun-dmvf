from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from .expansion import load, timeline
from .handoff_audit import audit_record
from .handoff_metrics import measure_batch, metrics_record
from .handoff_models import HandoffAudit, RecoveryCheck, RecoveryDispatch
from .models import PickupBatch, audit


def dispatch_record(row):
    evidence = audit_record(row.evidence)
    return {field: evidence[field] for field in ('station_name', 'station_code', 'shift')} | {
        'id': row.id, 'audit_id': row.audit_id, 'status': row.status, 'business_date': row.business_date,
        'headcount': row.headcount, 'plan_note': row.plan_note, 'evidence': evidence,
    }


def dispatch_detail(db, row):
    query = select(RecoveryCheck).where(RecoveryCheck.dispatch_id == row.id).options(
        joinedload(RecoveryCheck.batch),
    ).order_by(RecoveryCheck.id)
    return dispatch_record(row) | {
        'events': timeline(db, 'recovery', row.id),
        'checks': [metrics_record(check, row.evidence.sla_minutes) | {
            'business_date': check.batch.business_date, 'checked_by': check.checked_by,
            'created_at': check.created_at,
        } for check in db.scalars(query)],
    }


def dispatch_list(db):
    query = select(RecoveryDispatch).order_by(RecoveryDispatch.id.desc())
    return [dispatch_record(row) for row in db.scalars(query)]


def apply_plan(row, payload, anchor):
    if not 1 <= (payload.business_date - anchor).days <= 7:
        raise HTTPException(422, '补派须安排在交接批次或上次核验后的 1 至 7 个营业日内')
    row.business_date, row.headcount, row.plan_note = payload.business_date, payload.headcount, payload.note
    row.status = 'proposed'


def save(db, row, actor, event, **detail):
    db.flush()
    audit(db, actor, event, f'recovery:{row.id}', status=row.status, date=str(row.business_date), **detail)
    db.commit()
    return dispatch_detail(db, row)


def propose(db, payload, actor):
    evidence = load(db, HandoffAudit, payload.audit_id, '交接证据', lock=True)
    if evidence.verdict == 'clear':
        raise HTTPException(409, '交接证据已达标，无需补派')
    if db.scalar(select(RecoveryDispatch.id).where(RecoveryDispatch.audit_id == evidence.id)):
        raise HTTPException(409, '该交接证据已有补派单')
    row = RecoveryDispatch(audit_id=evidence.id)
    apply_plan(row, payload, evidence.batch.business_date)
    db.add(row)
    return save(db, row, actor, 'recovery_proposed', headcount=row.headcount, note=row.plan_note)


def replan(db, key, payload, actor):
    row = load(db, RecoveryDispatch, key, '补派单', lock=True)
    if row.status != 'replan':
        raise HTTPException(409, '只有核验异常的补派单可以重新排期')
    apply_plan(row, payload, row.business_date)
    return save(db, row, actor, 'recovery_replanned', headcount=row.headcount, note=row.plan_note)


def release(db, key, payload, actor):
    row = load(db, RecoveryDispatch, key, '补派单', lock=True)
    if row.status != 'proposed':
        raise HTTPException(409, '只有待派发的补派单可以派发')
    row.status = 'released'
    return save(db, row, actor, 'recovery_released', headcount=row.headcount, note=payload.note)


def verify(db, key, payload, actor):
    row = load(db, RecoveryDispatch, key, '补派单', lock=True)
    if row.status != 'released':
        raise HTTPException(409, '主管派发后才能提交补派核验')
    source = row.evidence.batch
    batch = db.scalar(select(PickupBatch).where(PickupBatch.code == payload.batch_code).with_for_update())
    if not batch or (batch.station_code, batch.shift, batch.business_date) != (
        source.station_code, source.shift, row.business_date,
    ):
        raise HTTPException(422, '核验批次须与补派单网点、营业日和班次一致')
    if db.scalar(select(RecoveryCheck.id).where(RecoveryCheck.batch_code == batch.code)):
        raise HTTPException(409, '该批次已用于补派核验')
    metrics = measure_batch(db, batch.code, row.evidence.sla_minutes)
    db.add(RecoveryCheck(dispatch_id=row.id, batch_code=batch.code, checked_by=actor, **metrics))
    row.status = 'verified' if metrics['verdict'] == 'clear' else 'replan'
    return save(db, row, actor, 'recovery_checked', batch=batch.code, note=payload.note)
