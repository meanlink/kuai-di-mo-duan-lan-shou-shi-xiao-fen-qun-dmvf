import logging
import sys
import time
from pathlib import Path

from sqlalchemy import select

from .clustering import analyze
from .db import cache, transaction
from .models import ClusterRun, audit

HEARTBEAT = Path('/work/pickup-worker-heartbeat')
log = logging.getLogger('pickup-worker')


def process_run():
    with transaction() as db:
        query = (select(ClusterRun).where(ClusterRun.state == 'queued').order_by(ClusterRun.id)
                 .limit(1).with_for_update(skip_locked=True))
        run = db.scalar(query)
        if not run:
            return
        try:
            run.result = analyze(run.snapshot, run.k, run.min_samples)
            run.state = 'review'
        except ValueError as error:
            run.error = str(error)
            run.state = 'failed'
        audit(db, 'worker', 'run_computed', run.id, state=run.state)
        log.info('Run %d → %s', run.id, run.state)


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
