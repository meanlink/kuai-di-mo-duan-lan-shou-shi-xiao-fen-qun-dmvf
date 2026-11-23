import logging
import sys
import time
from pathlib import Path

from sqlalchemy import select

from .clustering import analyze
from .db import cache, transaction
from .models import ClusterAttempt, ClusterRun, audit, utcnow

HEARTBEAT = Path('/work/pickup-worker-heartbeat')
log = logging.getLogger('pickup-worker')


def process_run():
    with transaction() as db:
        query = (select(ClusterAttempt).where(ClusterAttempt.state == 'queued').order_by(ClusterAttempt.id)
                 .limit(1).with_for_update(skip_locked=True))
        attempt = db.scalar(query)
        if not attempt:
            return
        attempt_id, run_id = attempt.id, attempt.run_id
        snapshot, k, minimum = attempt.run.snapshot, attempt.run.k, attempt.run.min_samples
    # 计算在事务外进行，避免长时间持锁挡住主管接管。
    try:
        result, error = analyze(snapshot, k, minimum), None
    except ValueError as exc:
        result, error = None, str(exc)
    with transaction() as db:
        run = db.scalar(select(ClusterRun).where(ClusterRun.id == run_id).with_for_update())
        attempt = db.scalar(select(ClusterAttempt).where(ClusterAttempt.id == attempt_id).with_for_update())
        if attempt.state != 'queued':
            # 该尝试已被主管接管作废，迟到的结果不得进入待确认。
            audit(db, 'worker', 'attempt_discarded', run.id, attempt=attempt.seq, state=attempt.state)
            log.info('Run %d attempt %d discarded (%s)', run_id, attempt.seq, attempt.state)
            return
        attempt.state = 'failed' if error else 'ready'
        attempt.result, attempt.error, attempt.finished_at = result, error, utcnow()
        run.state = 'failed' if error else 'review'
        run.result, run.error = result, error
        audit(db, 'worker', 'run_computed', run.id, attempt=attempt.seq, state=run.state)
        log.info('Run %d attempt %d → %s', run_id, attempt.seq, run.state)


def main():
    logging.basicConfig(level=logging.INFO)
    while True:
        try:
            cache.ping()
            process_run()
            heartbeat = HEARTBEAT.with_suffix('.tmp')
            heartbeat.write_text(str(time.time()))
            heartbeat.replace(HEARTBEAT)
        except Exception:
            log.exception('Worker loop failed')
        time.sleep(1)


if __name__ == '__main__':
    if sys.argv[1:] == ['health']:
        sys.exit(0 if HEARTBEAT.is_file() and time.time() - HEARTBEAT.stat().st_mtime < 12 else 1)
    main()
