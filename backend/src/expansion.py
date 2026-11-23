from sqlalchemy import case, func, select
from sqlalchemy.orm import joinedload
from fastapi import HTTPException

from .expansion_models import ShiftFollowup, ShiftSupport
from .models import AuditEvent, ClusterRun, PickupBatch, PickupScan, RemediationTask, audit

MIN_SAMPLE = 12
MAX_LATE_PERCENT = 25
MIN_IMPROVEMENT_POINTS = 10


def load(db, model, key, label, *, lock=False):
    query = select(model).where(model.id == key)
    row = db.scalar(query.with_for_update() if lock else query)
    if row is None:
        raise HTTPException(404, f'{label}不存在')
    return row


def timeline(db, kind, key):
    query = select(AuditEvent).where(AuditEvent.subject == f'{kind}:{key}').order_by(AuditEvent.id)
    return [dict(actor=row.actor, action=row.action, created_at=row.created_at, **row.detail)
            for row in db.scalars(query)]


def snapshot(db, station, shift, start, end, sla):
    query = (
        select(PickupBatch.code, func.count(PickupScan.parcel_code),
               func.sum(case((PickupScan.elapsed_minutes > sla, 1), else_=0)))
        .join(PickupScan, PickupScan.batch_code == PickupBatch.code)
        .where(PickupBatch.station_code == station, PickupBatch.shift == shift,
               PickupBatch.business_date.between(start, end))
        .group_by(PickupBatch.code).order_by(PickupBatch.code)
    )
    rows = db.execute(query).all()
    return sum(row[1] for row in rows), sum(int(row[2]) for row in rows), [row[0] for row in rows]


def measurement(count, late, batches):
    if count is None:
        return None
    return {'count': count, 'late': late, 'late_rate': round(100 * late / count, 2), 'batches': batches}


def criteria(row):
    if row.measured_count is None:
        return None
    before, after = row.baseline_count, row.measured_count
    # Compare the exact proportions so display rounding cannot change the verdict.
    improvement = 100 * (row.baseline_late * after - row.measured_late * before)
    return {
        'improvement_points': round(improvement / (before * after), 2),
        'within_limit': 100 * row.measured_late <= MAX_LATE_PERCENT * after,
        'sufficient_drop': improvement >= MIN_IMPROVEMENT_POINTS * before * after,
    }


def followup_record(row):
    task = row.task
    return {
        'id': row.id, 'task_id': row.task_id, 'run_id': task.run_id, 'station_code': task.station_code,
        'station_name': task.station.name, 'shift': row.shift, 'status': row.status,
        'start_date': row.start_date, 'end_date': row.end_date, 'sla_minutes': row.sla_minutes,
        'baseline': measurement(row.baseline_count, row.baseline_late, row.baseline_batches),
        'measured': measurement(row.measured_count, row.measured_late, row.measured_batches),
        'criteria': criteria(row), 'review_note': row.review_note,
    }


def followup_detail(db, row):
    support_id = db.scalar(select(ShiftSupport.id).where(ShiftSupport.followup_id == row.id))
    return followup_record(row) | {'support_id': support_id, 'events': timeline(db, 'followup', row.id)}


def followup_list(db):
    query = select(ShiftFollowup).options(joinedload(ShiftFollowup.task).joinedload(RemediationTask.station))
    return [followup_record(row) for row in db.scalars(query.order_by(ShiftFollowup.id.desc()))]


def schedule_followup(db, payload, actor):
    task = load(db, RemediationTask, payload.task_id, '整改单', lock=True)
    if task.status not in ('resolved', 'closed'):
        raise HTTPException(409, '请先提交整改单整改证据')
    if db.scalar(select(ShiftFollowup.id).where(ShiftFollowup.task_id == task.id)):
        raise HTTPException(409, '该整改单已有复测计划')
    run = db.get(ClusterRun, task.run_id)
    if not (run.end_date < payload.start <= payload.end and (payload.end - run.end_date).days <= 14):
        raise HTTPException(422, '复测须安排在原分群窗口结束后的 14 天内')
    original = next(item for item in run.snapshot if item['code'] == task.station_code)
    sla = original['sla_minutes']
    count, late, batches = snapshot(db, task.station_code, payload.shift, run.start_date, run.end_date, sla)
    if count < MIN_SAMPLE:
        raise HTTPException(409, f'该班次在原分群窗口内只有 {count} 张面单，基线至少需要 {MIN_SAMPLE} 张')
    row = ShiftFollowup(task_id=task.id, shift=payload.shift, start_date=payload.start, end_date=payload.end,
                       sla_minutes=sla, baseline_count=count, baseline_late=late, baseline_batches=batches)
    db.add(row)
    db.flush()
    audit(db, actor, 'followup_scheduled', f'followup:{row.id}', status=row.status, task_id=task.id)
    db.commit()
    return followup_detail(db, row)


def measure_followup(db, key, actor):
    row = load(db, ShiftFollowup, key, '班次复测', lock=True)
    if row.status != 'scheduled':
        raise HTTPException(409, '该计划已冻结复测样本')
    count, late, batches = snapshot(db, row.task.station_code, row.shift, row.start_date, row.end_date, row.sla_minutes)
    if count < MIN_SAMPLE:
        raise HTTPException(409, f'复测窗口内同网点同班次只有 {count} 张面单，至少需要 {MIN_SAMPLE} 张')
    row.measured_count, row.measured_late, row.measured_batches = count, late, batches
    row.status = 'measured'
    audit(db, actor, 'followup_measured', f'followup:{row.id}', status=row.status, count=count, late=late)
    db.commit()
    return followup_detail(db, row)


def review_followup(db, key, payload, actor):
    row = load(db, ShiftFollowup, key, '班次复测', lock=True)
    if row.status != 'measured':
        raise HTTPException(409, '只有待签核的复测可以签核')
    result = criteria(row)
    row.status = 'passed' if result['within_limit'] and result['sufficient_drop'] else 'failed'
    row.review_note = payload.note
    audit(db, actor, 'followup_reviewed', f'followup:{row.id}', status=row.status, note=payload.note)
    db.commit()
    return followup_detail(db, row)


def support_record(row):
    followup = row.followup
    return {
        'id': row.id, 'followup_id': row.followup_id, 'station_code': followup.task.station_code,
        'station_name': followup.task.station.name, 'shift': followup.shift, 'status': row.status,
        'business_date': row.business_date, 'headcount': row.headcount, 'request_note': row.request_note,
        'decision_note': row.decision_note, 'actual_headcount': row.actual_headcount,
        'evidence_batch': row.evidence_batch, 'completion_note': row.completion_note,
    }


def support_detail(db, row):
    return support_record(row) | {'events': timeline(db, 'support', row.id)}


def support_list(db):
    query = select(ShiftSupport).options(
        joinedload(ShiftSupport.followup).joinedload(ShiftFollowup.task).joinedload(RemediationTask.station))
    return [support_record(row) for row in db.scalars(query.order_by(ShiftSupport.id.desc()))]


def apply_plan(row, followup, payload):
    if not 1 <= (payload.business_date - followup.end_date).days <= 14:
        raise HTTPException(422, '支援营业日须在复测窗口结束后的 14 天内')
    row.business_date, row.headcount, row.request_note = payload.business_date, payload.headcount, payload.note
    row.status = 'requested'
    row.decision_note = None


def save_support(db, row, actor, event, **detail):
    db.flush()
    audit(db, actor, event, f'support:{row.id}', status=row.status, **detail)
    db.commit()
    return support_detail(db, row)


def request_support(db, payload, actor):
    followup = load(db, ShiftFollowup, payload.followup_id, '班次复测', lock=True)
    if followup.status != 'failed':
        raise HTTPException(409, '须先由主管签核为未达标')
    if db.scalar(select(ShiftSupport.id).where(ShiftSupport.followup_id == followup.id)):
        raise HTTPException(409, '该复测已有支援单，请在原单上处理')
    row = ShiftSupport(followup_id=followup.id)
    apply_plan(row, followup, payload)
    db.add(row)
    return save_support(db, row, actor, 'support_requested', date=str(row.business_date),
                        headcount=row.headcount, note=row.request_note)


def resubmit_support(db, key, payload, actor):
    row = load(db, ShiftSupport, key, '支援单', lock=True)
    if row.status != 'returned':
        raise HTTPException(409, '仅退回的支援单可修改后重报')
    apply_plan(row, row.followup, payload)
    return save_support(db, row, actor, 'support_resubmitted', date=str(row.business_date),
                        headcount=row.headcount, note=row.request_note)


def decide_support(db, key, payload, actor):
    row = load(db, ShiftSupport, key, '支援单', lock=True)
    if row.status != 'requested':
        raise HTTPException(409, '只有待审批的支援单可以审批')
    row.status, row.decision_note = payload.decision, payload.note
    return save_support(db, row, actor, 'support_decided', note=row.decision_note)


def complete_support(db, key, payload, actor):
    row = load(db, ShiftSupport, key, '支援单', lock=True)
    if row.status != 'approved':
        raise HTTPException(409, '支援单审批通过后才能核销')
    if payload.actual_headcount > row.headcount:
        raise HTTPException(422, '实到人数不能超过批准人数')
    batch = db.scalar(select(PickupBatch).where(PickupBatch.code == payload.evidence_batch).with_for_update())
    if (not batch or (batch.station_code, batch.shift, batch.business_date) !=
            (row.followup.task.station_code, row.followup.shift, row.business_date)):
        raise HTTPException(422, '支援批次须与支援单网点、营业日和班次一致')
    if not db.scalar(select(PickupScan.parcel_code).where(PickupScan.batch_code == batch.code).limit(1)):
        raise HTTPException(422, '支援批次须已有扫描面单')
    if db.scalar(select(ShiftSupport.id).where(ShiftSupport.evidence_batch == batch.code)):
        raise HTTPException(409, '该批次已经用于另一张支援单')
    row.status, row.actual_headcount = 'completed', payload.actual_headcount
    row.evidence_batch, row.completion_note = batch.code, payload.note
    return save_support(db, row, actor, 'support_completed', batch=batch.code,
                        headcount=row.actual_headcount, note=row.completion_note)
