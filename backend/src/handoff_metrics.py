from fastapi import HTTPException
from sqlalchemy import case, func, select

from .expansion import MAX_LATE_PERCENT, MIN_SAMPLE
from .models import PickupScan


def measure_batch(db, batch_code, sla_minutes):
    query = select(
        func.count(),
        func.sum(case((PickupScan.elapsed_minutes > sla_minutes, 1), else_=0)),
        func.max(PickupScan.elapsed_minutes),
    ).where(PickupScan.batch_code == batch_code)
    count, late, worst = db.execute(query).one()
    if not count:
        raise HTTPException(422, '该批次没有可核验的扫描面单')
    late = int(late)
    if count < MIN_SAMPLE:
        verdict = 'insufficient'
    elif 100 * late > MAX_LATE_PERCENT * count:
        verdict = 'breach'
    else:
        verdict = 'clear'
    return dict(scan_count=count, late_count=late, worst_minutes=worst, verdict=verdict)


def metrics_record(row, sla_minutes):
    return {
        'batch_code': row.batch_code, 'scan_count': row.scan_count, 'late_count': row.late_count,
        'worst_minutes': row.worst_minutes, 'verdict': row.verdict, 'sla_minutes': sla_minutes,
        'late_rate': round(100 * row.late_count / row.scan_count, 2),
        'min_sample': MIN_SAMPLE, 'max_late_percent': MAX_LATE_PERCENT,
    }
