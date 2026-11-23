import hashlib
import json
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from .clustering import analyze
from .db import transaction
from .models import ClusterAttempt, ClusterRun, RemediationTask, audit, utcnow
from .scans import station_profiles

# 排队中的计算超过该时长未返回即视为卡住，主管可接管。可用 RUN_STUCK_SECONDS 调整。
STUCK_SECONDS = int(os.getenv('RUN_STUCK_SECONDS', '60'))


def run_record(run):
    return {name: getattr(run, name) for name in (
        'id', 'start_date', 'end_date', 'k', 'min_samples', 'state', 'fingerprint', 'error',
        'created_by', 'reviewed_by', 'created_at', 'reviewed_at',
    )}


def attempts_of(db, run_id):
    query = select(ClusterAttempt).where(ClusterAttempt.run_id == run_id).order_by(ClusterAttempt.seq)
    return db.scalars(query).all()


def takeover_status(run, active):
    """主管能否接管该运行的计算。已派单的一律禁止，计算完成的直接确认即可。"""
    if run.state == 'approved':
        return {'eligible': False, 'reason': '整改单已派发，该分群不能再接管'}
    if run.state == 'review':
        return {'eligible': False, 'reason': '计算已完成，请直接确认分群结果'}
    if run.state == 'failed':
        return {'eligible': True, 'reason': None}
    waited = (utcnow() - active.created_at).total_seconds() if active else STUCK_SECONDS
    if waited >= STUCK_SECONDS:
        return {'eligible': True, 'reason': None}
    return {'eligible': False, 'reason': f'计算尚未卡住，约 {int(STUCK_SECONDS - waited)} 秒后可接管'}


def attempt_record(attempt, active_id):
    return {
        'id': attempt.id, 'seq': attempt.seq, 'origin': attempt.origin, 'state': attempt.state,
        'error': attempt.error, 'created_by': attempt.created_by,
        'created_at': attempt.created_at, 'finished_at': attempt.finished_at,
        'dispatched': attempt.dispatched_at is not None, 'active': attempt.id == active_id,
    }


def run_detail(db, run):
    if run is None:
        raise HTTPException(404, '分群运行不存在')
    tasks = db.scalars(select(RemediationTask).where(RemediationTask.run_id == run.id)).all()
    attempts = attempts_of(db, run.id)
    active = attempts[-1] if attempts else None
    return run_record(run) | {
        'result': run.result,
        'manual_reviews': {
            task.station_code: {'task_id': task.id, 'segment': task.segment, 'note': task.review_note}
            for task in tasks if task.source == 'manual'
        },
        'attempts': [attempt_record(row, active.id if active else 0) for row in attempts],
        'active_attempt_id': active.id if active else None,
        'approved_attempt_id': next((row.id for row in attempts if row.dispatched_at), None),
        'takeover': takeover_status(run, active),
    }


def queue(db, request, actor):
    snapshot = station_profiles(db, request)
    params = request.model_dump(mode='json')
    fingerprint = hashlib.sha256(json.dumps([params, snapshot], sort_keys=True).encode()).hexdigest()
    existing = db.scalar(select(ClusterRun).where(ClusterRun.fingerprint == fingerprint))
    if existing:
        return run_detail(db, existing)
    run = ClusterRun(start_date=request.start, end_date=request.end, k=request.k, min_samples=request.min_samples,
                     snapshot=snapshot, fingerprint=fingerprint, created_by=actor)
    db.add(run)
    try:
        db.flush()
        db.add(ClusterAttempt(run_id=run.id, seq=1, origin='initial', created_by=actor))
        audit(db, actor, 'run_queued', run.id, **params, fingerprint=fingerprint)
        db.commit()
    except IntegrityError as error:
        db.rollback()
        existing = db.scalar(select(ClusterRun).where(ClusterRun.fingerprint == fingerprint))
        if existing is None:
            raise error
        run = existing
    return run_detail(db, run)


def locked_run(db, run_id):
    run = db.scalar(select(ClusterRun).where(ClusterRun.id == run_id).with_for_update())
    if not run:
        raise HTTPException(404, '分群运行不存在')
    return run


def create_task(db, run, station, segment, source, note=None):
    due_date = datetime.now(ZoneInfo('Asia/Shanghai')).date() + timedelta(days=3)
    task = RemediationTask(run_id=run.id, station_code=station, segment=segment['id'],
                           source=source, review_note=note, action=segment['action'], due_date=due_date)
    db.add(task)
    return task


def approve(db, run_id, payload, actor):
    run = locked_run(db, run_id)
    if run.state != 'review':
        raise HTTPException(409, '只有待主管确认的分群可以发布')
    attempts = attempts_of(db, run.id)
    active = attempts[-1] if attempts else None
    if active is None or active.id != payload.attempt_id or active.state != 'ready':
        raise HTTPException(409, '你看到的结果已被新的计算替换，请刷新后再确认')
    alerts = {row['id']: row for row in run.result['segments'] if row['alert']}
    issued = []
    for station in run.result['members']:
        if station['segment'] in alerts:
            create_task(db, run, station['code'], alerts[station['segment']], 'cluster')
            issued.append(station['code'])
    active.dispatched_at = utcnow()
    run.state, run.reviewed_by, run.reviewed_at = 'approved', actor, utcnow()
    audit(db, actor, 'run_approved', run.id, attempt=active.seq, issued=issued)
    db.commit()
    return run_detail(db, run)


def takeover(db, run_id, payload, actor):
    """主管接管卡住或失败的计算：用冻结样本同步重算，原排队尝试作废。

    request_key 是接管请求的幂等键，同一次请求重试不会新增尝试。
    """
    run = locked_run(db, run_id)
    # 幂等检查放在行锁内：并发下同键请求只受理一次，重试返回首次受理的结果。
    existing = db.scalar(select(ClusterAttempt).where(ClusterAttempt.request_key == payload.request_key))
    if existing:
        if existing.run_id != run_id:
            raise HTTPException(409, '该接管请求标识已用于其他分群')
        return run_detail(db, run)
    attempts = attempts_of(db, run.id)
    active = attempts[-1] if attempts else None
    status = takeover_status(run, active)
    if not status['eligible']:
        raise HTTPException(409, status['reason'])
    if active and active.state == 'queued':
        active.state, active.finished_at = 'superseded', utcnow()
        audit(db, actor, 'attempt_superseded', run.id, attempt=active.seq)
    attempt = ClusterAttempt(run_id=run.id, seq=active.seq + 1 if active else 1, origin='takeover',
                             request_key=payload.request_key, created_by=actor)
    db.add(attempt)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(ClusterAttempt).where(ClusterAttempt.request_key == payload.request_key))
        if existing and existing.run_id == run_id:
            return run_detail(db, db.get(ClusterRun, run_id))
        raise HTTPException(409, '该接管请求标识已用于其他分群')
    try:
        attempt.result = analyze(run.snapshot, run.k, run.min_samples)
        attempt.state = 'ready'
        run.state, run.result, run.error = 'review', attempt.result, None
    except ValueError as error:
        attempt.state, attempt.error = 'failed', str(error)
        run.state, run.result, run.error = 'failed', None, str(error)
    attempt.finished_at = utcnow()
    audit(db, actor, 'run_taken_over', run.id, attempt=attempt.seq, state=attempt.state,
          superseded=active.seq if active else None)
    db.commit()
    return run_detail(db, run)


def backfill_attempts():
    """为建表前已存在的运行补登第一次计算尝试，保持旧数据可确认、可追溯。"""
    states = {'queued': 'queued', 'review': 'ready', 'approved': 'ready', 'failed': 'failed'}
    with transaction() as db:
        for run in db.scalars(select(ClusterRun)).all():
            if db.scalar(select(ClusterAttempt.id).where(ClusterAttempt.run_id == run.id).limit(1)):
                continue
            db.add(ClusterAttempt(
                run_id=run.id, seq=1, origin='initial', state=states[run.state],
                result=run.result, error=run.error, created_by=run.created_by, created_at=run.created_at,
                finished_at=None if run.state == 'queued' else run.reviewed_at or run.created_at,
                dispatched_at=run.reviewed_at if run.state == 'approved' else None))


def manual_review(db, run_id, code, payload, actor):
    run = locked_run(db, run_id)
    if run.state != 'approved':
        raise HTTPException(409, '请先由主管确认分群，再处理低样本网点')
    station = next((row for row in run.result['excluded'] if row['code'] == code), None)
    if not station or station['count'] == 0:
        raise HTTPException(409, '当前网点不具备人工确认条件，零样本网点须先补采')
    segment = next((row for row in run.result['segments'] if row['id'] == payload.segment), None)
    if segment is None:
        raise HTTPException(422, '所选分群不存在')
    existing = db.scalar(select(RemediationTask.id).where(
        RemediationTask.run_id == run.id, RemediationTask.station_code == code))
    if existing:
        raise HTTPException(409, '该网点已确认并派单')
    task = create_task(db, run, code, segment, 'manual', payload.note)
    db.flush()
    audit(db, actor, 'station_manually_reviewed', run.id, station=code, segment=segment['id'], task_id=task.id)
    db.commit()
    return task_record(task)


def task_record(task):
    return {
        **{name: getattr(task, name) for name in (
            'id', 'run_id', 'station_code', 'segment', 'source', 'status', 'action',
            'review_note', 'evidence', 'due_date', 'created_at',
        )}, 'station_name': task.station.name, 'lead': task.station.lead,
    }


def task_list(db):
    query = select(RemediationTask).options(selectinload(RemediationTask.station)).order_by(RemediationTask.id.desc())
    return [task_record(task) for task in db.scalars(query)]


def advance_task(db, task_id, payload, user):
    task = db.scalar(select(RemediationTask).where(RemediationTask.id == task_id).with_for_update())
    if task is None:
        raise HTTPException(404, '整改任务不存在')
    if payload.status == 'closed' and user.role != 'admin':
        raise HTTPException(403, '只有主管可以复核结案')
    if {'open': 'doing', 'doing': 'resolved', 'resolved': 'closed'}.get(task.status) != payload.status:
        raise HTTPException(409, '请按待处理、处理中、待复核、已结案的顺序操作')
    if payload.status == 'resolved':
        if len(payload.evidence or '') < 12:
            raise HTTPException(422, '提交复核时，请填写至少 12 字的整改证据')
        task.evidence = payload.evidence
    audit(db, user.username, 'task_advanced', task.id, from_status=task.status, to_status=payload.status)
    task.status = payload.status
    db.commit()
    return task_record(task)
