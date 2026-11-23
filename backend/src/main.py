import logging
import os
import time
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from sqlalchemy.orm import selectinload

from scripts.seed_demo import seed
from . import review, scans
from .auth import allow, current_user, login
from .db import Base, cache, engine, session
from .expansion_routes import router as expansion_router
from .handoff_routes import router as handoff_router
from .models import AuditEvent, ClusterRun, PickupBatch, RemediationTask
from .schemas import AdvanceTask, ImportBatch, Login, ManualReview, RunRequest, Window, validate_window

log = logging.getLogger('uvicorn.error')


@asynccontextmanager
async def lifespan(_app):
    Base.metadata.create_all(engine)
    if os.getenv('SEED_DEMO', 'true').lower() == 'true':
        try:
            seed()
        except Exception:
            log.exception('Demo seed failed. Run python -m scripts.seed_demo to retry.')
    yield


app = FastAPI(title='快递末端揽收时效分群', lifespan=lifespan)
app.include_router(expansion_router)
app.include_router(handoff_router)


@app.middleware('http')
async def request_id(request, call_next):
    identifier = uuid4().hex[:12]
    start = time.monotonic()
    response = await call_next(request)
    response.headers['X-Request-ID'] = identifier
    log.info('%s %s %s %.1fms [%s]', request.method, request.url.path, response.status_code,
             (time.monotonic() - start) * 1000, identifier)
    return response


@app.middleware('http')
async def control_cache(request, call_next):
    response = await call_next(request)
    response.headers['Cache-Control'] = 'no-store'
    if request.url.path == '/auth/login':
        response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


@app.exception_handler(RequestValidationError)
async def validation_error(_request, error):
    fields = [{'field': '.'.join(map(str, item['loc'])), 'msg': item['msg']} for item in error.errors()]
    return JSONResponse(status_code=422, content={'detail': fields})


@app.get('/health')
def health(db=Depends(session)):
    db.execute(text('SELECT 1'))
    cache.ping()
    return {'ok': True}


@app.post('/auth/login')
def login_route(payload: Login, request: Request, db=Depends(session)):
    return login(db, payload, request.client.host if request.client else 'unknown')


@app.get('/stations')
def profiles(window: Window = Depends(), db=Depends(session), _user=Depends(current_user)):
    rows = scans.station_profiles(db, validate_window(window))
    return {'stations': rows, 'observations': sum(row['count'] for row in rows),
            'below_standard_sample': sum(0 < row['count'] < 24 for row in rows),
            'unobserved': sum(row['count'] == 0 for row in rows)}


@app.get('/batches')
def batches(station_code: str | None = None, window: Window = Depends(), db=Depends(session), _user=Depends(current_user)):
    return scans.list_batches(db, validate_window(window), station_code)


@app.get('/batches/{code}')
def batch_detail(code: str, db=Depends(session), _user=Depends(current_user)):
    batch = db.scalar(select(PickupBatch).options(selectinload(PickupBatch.scans)).where(PickupBatch.code == code))
    if batch is None:
        raise HTTPException(404, '揽收批次不存在')
    return scans.batch_record(batch, include_scans=True)


@app.post('/batches', status_code=201)
def import_batch(payload: ImportBatch, db=Depends(session), user=Depends(allow('analyst', 'admin'))):
    return scans.import_batch(db, payload, user.username)


@app.get('/runs')
def runs(db=Depends(session), _user=Depends(current_user)):
    return [review.run_record(run) for run in db.scalars(select(ClusterRun).order_by(ClusterRun.id.desc()).limit(50))]


@app.post('/runs', status_code=202)
def queue(payload: RunRequest, db=Depends(session), user=Depends(allow('admin'))):
    return review.queue(db, validate_window(payload), user.username)


@app.get('/runs/{run_id}')
def run_detail(run_id: int, db=Depends(session), _user=Depends(current_user)):
    return review.run_detail(db, db.get(ClusterRun, run_id))


@app.post('/runs/{run_id}/approve')
def approve(run_id: int, db=Depends(session), user=Depends(allow('admin'))):
    return review.approve(db, run_id, user.username)


@app.post('/runs/{run_id}/manual/{station_code}', status_code=201)
def manual(run_id: int, station_code: str, payload: ManualReview, db=Depends(session), user=Depends(allow('admin'))):
    return review.manual_review(db, run_id, station_code, payload, user.username)


@app.get('/tasks')
def tasks(db=Depends(session), _user=Depends(current_user)):
    return review.task_list(db)


@app.get('/tasks/{task_id}')
def task_detail(task_id: int, db=Depends(session), _user=Depends(current_user)):
    task = db.get(RemediationTask, task_id)
    if task is None:
        raise HTTPException(404, '整改任务不存在')
    events = db.scalars(select(AuditEvent).where(AuditEvent.subject == str(task_id), AuditEvent.action == 'task_advanced')
                        .order_by(AuditEvent.id))
    return review.task_record(task) | {
        'events': [{'actor': row.actor, 'created_at': row.created_at, **row.detail} for row in events],
    }


@app.patch('/tasks/{task_id}')
def advance(task_id: int, payload: AdvanceTask, db=Depends(session), user=Depends(allow('analyst', 'admin'))):
    return review.advance_task(db, task_id, payload, user)
