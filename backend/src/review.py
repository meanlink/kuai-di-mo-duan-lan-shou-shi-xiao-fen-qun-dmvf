import hashlib
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from .models import ClusterRun, RemediationTask, audit, utcnow
from .scans import station_profiles


def run_record(run):
    return {name: getattr(run, name) for name in (
        'id', 'start_date', 'end_date', 'k', 'min_samples', 'state', 'fingerprint', 'error',
        'created_by', 'reviewed_by', 'created_at', 'reviewed_at',
    )}


def run_detail(db, run):
    if run is None:
        raise HTTPException(404, '分群运行不存在')
    tasks = db.scalars(select(RemediationTask).where(RemediationTask.run_id == run.id)).all()
    return run_record(run) | {
        'result': run.result,
        'manual_reviews': {
            task.station_code: {'task_id': task.id, 'segment': task.segment, 'note': task.review_note}
            for task in tasks if task.source == 'manual'
        },
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


def approve(db, run_id, actor):
    run = locked_run(db, run_id)
    if run.state != 'review':
        raise HTTPException(409, '只有待主管确认的分群可以发布')
    alerts = {row['id']: row for row in run.result['segments'] if row['alert']}
    issued = []
    for station in run.result['members']:
        if station['segment'] in alerts:
            create_task(db, run, station['code'], alerts[station['segment']], 'cluster')
            issued.append(station['code'])
    run.state, run.reviewed_by, run.reviewed_at = 'approved', actor, utcnow()
    audit(db, actor, 'run_approved', run.id, issued=issued)
    db.commit()
    return run_detail(db, run)


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
