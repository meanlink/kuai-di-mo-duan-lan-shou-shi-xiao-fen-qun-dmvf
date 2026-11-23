"""接管相关 HTTP 接口的冒烟测试：路由、请求校验与状态流转。"""
from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from src import main
from src.auth import current_user
from src.models import ClusterAttempt, utcnow

from .support import engine, seed_network

WINDOW = {'start': '2026-11-16', 'end': '2026-11-21'}


@pytest.fixture
def client(db, monkeypatch):
    monkeypatch.setattr(main, 'engine', engine)  # lifespan 的建表指向测试库
    monkeypatch.setenv('SEED_DEMO', 'false')

    def override_session():
        yield db

    main.app.dependency_overrides[main.session] = override_session
    main.app.dependency_overrides[current_user] = lambda: SimpleNamespace(username='admin', role='admin')
    seed_network(db)
    with TestClient(main.app) as test_client:
        yield test_client
    main.app.dependency_overrides.clear()


def make_stuck(db, run_id):
    attempt = db.scalars(select(ClusterAttempt).where(ClusterAttempt.run_id == run_id)).one()
    attempt.created_at = utcnow() - timedelta(seconds=120)
    db.commit()


def test_takeover_and_approve_flow(client, db):
    queued = client.post('/runs', json={**WINDOW, 'k': 3, 'min_samples': 12})
    assert queued.status_code == 202
    run_id = queued.json()['id']
    assert queued.json()['attempts'][0]['origin'] == 'initial'

    detail = client.get(f'/runs/{run_id}').json()
    assert detail['takeover']['eligible'] is False  # 未卡住不能接管

    early = client.post(f'/runs/{run_id}/takeover', json={'request_key': 'api-key-0001'})
    assert early.status_code == 409

    make_stuck(db, run_id)
    taken = client.post(f'/runs/{run_id}/takeover', json={'request_key': 'api-key-0001'})
    assert taken.status_code == 200
    body = taken.json()
    assert body['state'] == 'review'
    assert [row['state'] for row in body['attempts']] == ['superseded', 'ready']

    replay = client.post(f'/runs/{run_id}/takeover', json={'request_key': 'api-key-0001'})
    assert replay.status_code == 200 and len(replay.json()['attempts']) == 2

    assert client.post(f'/runs/{run_id}/approve', json={}).status_code == 422
    stale = client.post(f'/runs/{run_id}/approve', json={'attempt_id': body['attempts'][0]['id']})
    assert stale.status_code == 409

    approved = client.post(f'/runs/{run_id}/approve', json={'attempt_id': body['active_attempt_id']})
    assert approved.status_code == 200
    assert approved.json()['state'] == 'approved'
    assert approved.json()['approved_attempt_id'] == body['active_attempt_id']

    late = client.post(f'/runs/{run_id}/takeover', json={'request_key': 'api-key-0002'})
    assert late.status_code == 409  # 已派单不能再接管


def test_routes_require_manager_role(client):
    main.app.dependency_overrides[current_user] = lambda: SimpleNamespace(username='analyst', role='analyst')
    queued = client.post('/runs', json={**WINDOW, 'k': 3, 'min_samples': 12})
    assert queued.status_code == 403  # 网点运营不能发起分群，更不能接管
