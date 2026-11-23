"""测试共享的 SQLite 会话与演示网点数据。"""
from contextlib import contextmanager
from datetime import date, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.models import PickupBatch, PickupScan, Station, User

engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
TestSession = sessionmaker(engine, expire_on_commit=False)


@contextmanager
def tx():
    with TestSession.begin() as db:
        yield db


def seed_network(db, elapsed=(30, 40, 90, 95, 100), count=12):
    """5 家网点，前两家准时、后三家严重超时，特征两两不同，保证 KMeans 可收敛。"""
    db.add(User(username='admin', role='admin', password_hash='x'))
    for index, minutes in enumerate(elapsed, 1):
        code = f'HD-{index:02d}'
        db.add(Station(code=code, name=f'网点{index}', region='测试片区', lead='李某',
                       route_type='社区线', sla_minutes=60))
        batch = PickupBatch(code=f'B-{code}', station_code=code, business_date=date(2026, 11, 18),
                            shift='morning', source_name='demo.csv', recorded_by='admin')
        for n in range(count):
            planned = datetime(2026, 11, 18, 10, 0) + timedelta(minutes=n)
            batch.scans.append(PickupScan(parcel_code=f'P-{code}-{n:03}', planned_at=planned,
                                          scanned_at=planned + timedelta(minutes=minutes),
                                          elapsed_minutes=minutes))
        db.add(batch)
    db.commit()
