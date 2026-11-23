"""主管接管分群计算的端到端逻辑测试。

使用 SQLite 内存库；worker 与启动回填用到的 transaction 替换为测试会话。
运行方式：在 backend/ 下执行 `python -m pytest tests/`。
"""
from datetime import date, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select

from src import review, worker
from src.models import ClusterAttempt, ClusterRun, RemediationTask, utcnow
from src.schemas import ApproveRun, RunRequest, TakeoverRun

from .support import TestSession, seed_network

WINDOW = {'start': date(2026, 11, 16), 'end': date(2026, 11, 21)}


def queue_run(db, **overrides):
    payload = RunRequest(**WINDOW, k=overrides.pop('k', 3), min_samples=overrides.pop('min_samples', 12))
    return review.queue(db, payload, 'admin')


def make_stuck(db, run_id, seconds=120):
    attempt = db.scalars(select(ClusterAttempt).where(ClusterAttempt.run_id == run_id)).one()
    attempt.created_at = utcnow() - timedelta(seconds=seconds)
    db.commit()
    return attempt


def attempts(db, run_id):
    return db.scalars(select(ClusterAttempt).where(ClusterAttempt.run_id == run_id)
                      .order_by(ClusterAttempt.seq)).all()


def test_queue_creates_initial_attempt(db):
    seed_network(db)
    detail = queue_run(db)
    assert detail['state'] == 'queued'
    assert len(detail['attempts']) == 1
    first = detail['attempts'][0]
    assert (first['seq'], first['origin'], first['state']) == (1, 'initial', 'queued')
    assert detail['active_attempt_id'] == first['id']
    assert not detail['takeover']['eligible']  # 刚入队，尚未卡住
    again = queue_run(db)  # 同参数复用运行，不新增尝试
    assert again['id'] == detail['id'] and len(again['attempts']) == 1


def test_worker_computes_queued_attempt(db):
    seed_network(db)
    detail = queue_run(db)
    worker.process_run()
    db.expire_all()
    run = db.get(ClusterRun, detail['id'])
    attempt = attempts(db, run.id)[0]
    assert run.state == 'review' and attempt.state == 'ready'
    assert attempt.result == run.result and attempt.finished_at is not None


def test_takeover_stuck_run_uses_frozen_snapshot(db):
    seed_network(db)
    detail = queue_run(db)
    make_stuck(db, detail['id'])
    result = review.takeover(db, detail['id'], TakeoverRun(request_key='takeover-1'), 'admin')
    assert result['state'] == 'review'
    assert len(result['attempts']) == 2
    first, second = result['attempts']
    assert first['state'] == 'superseded'  # 原计算作废
    assert second['origin'] == 'takeover' and second['state'] == 'ready' and second['active']
    assert result['result'] is not None and result['active_attempt_id'] == second['id']


def test_takeover_rejects_healthy_queue(db):
    seed_network(db)
    detail = queue_run(db)
    with pytest.raises(HTTPException) as error:
        review.takeover(db, detail['id'], TakeoverRun(request_key='too-early'), 'admin')
    assert error.value.status_code == 409
    assert '尚未卡住' in error.value.detail


def test_takeover_replay_does_not_add_attempt(db):
    seed_network(db)
    detail = queue_run(db)
    make_stuck(db, detail['id'])
    review.takeover(db, detail['id'], TakeoverRun(request_key='same-key'), 'admin')
    replayed = review.takeover(db, detail['id'], TakeoverRun(request_key='same-key'), 'admin')
    assert replayed['state'] == 'review'
    assert len(replayed['attempts']) == 2  # 同一次请求重试不新增尝试


def test_request_key_cannot_be_reused_across_runs(db):
    seed_network(db)
    first, second = queue_run(db, k=3), queue_run(db, k=4)
    make_stuck(db, first['id'])
    make_stuck(db, second['id'])
    review.takeover(db, first['id'], TakeoverRun(request_key='shared-key'), 'admin')
    with pytest.raises(HTTPException) as error:
        review.takeover(db, second['id'], TakeoverRun(request_key='shared-key'), 'admin')
    assert error.value.status_code == 409


def test_failed_takeover_can_be_taken_over_again(db):
    seed_network(db, count=4)  # 全部低于 12 张门槛，重算必然失败
    detail = queue_run(db)
    make_stuck(db, detail['id'])
    failed = review.takeover(db, detail['id'], TakeoverRun(request_key='retry-key-1'), 'admin')
    assert failed['state'] == 'failed'
    assert failed['attempts'][-1]['state'] == 'failed'
    again = review.takeover(db, detail['id'], TakeoverRun(request_key='retry-key-2'), 'admin')
    assert again['state'] == 'failed'
    assert [row['seq'] for row in again['attempts']] == [1, 2, 3]


def test_late_worker_result_is_discarded_after_takeover(db, monkeypatch):
    seed_network(db)
    detail = queue_run(db)
    make_stuck(db, detail['id'])
    real_analyze = worker.analyze

    def slow_analyze(snapshot, k, minimum):
        # worker 计算期间，主管完成接管
        with TestSession() as other:
            review.takeover(other, detail['id'], TakeoverRun(request_key='racing-key'), 'admin')
        return real_analyze(snapshot, k, minimum)

    monkeypatch.setattr(worker, 'analyze', slow_analyze)
    worker.process_run()
    db.expire_all()
    run = db.get(ClusterRun, detail['id'])
    first, second = attempts(db, run.id)
    assert run.state == 'review'
    assert first.state == 'superseded' and first.result is None  # 迟到结果未进入待确认
    assert second.state == 'ready' and run.result == second.result


def test_approve_only_accepts_the_seen_attempt(db):
    seed_network(db)
    detail = queue_run(db)
    worker.process_run()
    db.expire_all()
    seen = review.run_detail(db, db.get(ClusterRun, detail['id']))['active_attempt_id']
    with pytest.raises(HTTPException) as error:
        review.approve(db, detail['id'], ApproveRun(attempt_id=seen + 999), 'admin')
    assert error.value.status_code == 409
    done = review.approve(db, detail['id'], ApproveRun(attempt_id=seen), 'admin')
    assert done['state'] == 'approved'
    assert done['approved_attempt_id'] == seen
    dispatched = [row for row in done['attempts'] if row['dispatched']]
    assert len(dispatched) == 1 and dispatched[0]['id'] == seen
    assert db.scalars(select(RemediationTask)).all()  # 超时群已派单


def test_stale_approve_rejected_after_takeover(db):
    seed_network(db)
    detail = queue_run(db)
    make_stuck(db, detail['id'])
    stale = review.run_detail(db, db.get(ClusterRun, detail['id']))['active_attempt_id']
    review.takeover(db, detail['id'], TakeoverRun(request_key='tk-first'), 'admin')
    with pytest.raises(HTTPException) as error:
        review.approve(db, detail['id'], ApproveRun(attempt_id=stale), 'admin')
    assert error.value.status_code == 409
    current = review.run_detail(db, db.get(ClusterRun, detail['id']))['active_attempt_id']
    done = review.approve(db, detail['id'], ApproveRun(attempt_id=current), 'admin')
    assert done['state'] == 'approved'


def test_approved_run_cannot_be_taken_over(db):
    seed_network(db)
    detail = queue_run(db)
    worker.process_run()
    db.expire_all()
    seen = review.run_detail(db, db.get(ClusterRun, detail['id']))['active_attempt_id']
    review.approve(db, detail['id'], ApproveRun(attempt_id=seen), 'admin')
    with pytest.raises(HTTPException) as error:
        review.takeover(db, detail['id'], TakeoverRun(request_key='too-late'), 'admin')
    assert error.value.status_code == 409
    assert '不能再接管' in error.value.detail


def test_backfill_attempts_for_legacy_runs(db):
    seed_network(db)
    detail = queue_run(db)
    db.execute(delete(ClusterAttempt))  # 模拟建表前的旧运行
    db.commit()
    review.backfill_attempts()
    attempt = attempts(db, detail['id'])[0]
    assert attempt.seq == 1 and attempt.state == 'queued' and attempt.origin == 'initial'
    worker.process_run()  # 补登后旧运行仍可被计算
    db.expire_all()
    assert db.get(ClusterRun, detail['id']).state == 'review'


def test_backfill_marks_approved_run_dispatched(db):
    seed_network(db)
    detail = queue_run(db)
    worker.process_run()
    db.expire_all()
    seen = review.run_detail(db, db.get(ClusterRun, detail['id']))['active_attempt_id']
    review.approve(db, detail['id'], ApproveRun(attempt_id=seen), 'admin')
    db.execute(delete(ClusterAttempt))
    db.commit()
    review.backfill_attempts()
    attempt = attempts(db, detail['id'])[0]
    assert attempt.state == 'ready' and attempt.dispatched_at is not None
