from datetime import date, datetime, time, timedelta
from random import Random

from sqlalchemy.dialects.mysql import insert

from src.auth import password_hash
from src.db import transaction
from src.models import PickupBatch, PickupScan, Station, User

DEMO_PASSWORD = 'Pickup1044!'
ACCOUNTS = ['admin', 'analyst', 'viewer']
STATIONS = [
    ('HD-01', '江陵路直营网点', '滨江片区', '周嘉', '写字楼线', 60, 24, 10),
    ('HD-02', '滨盛路揽收站', '滨江片区', '徐倩', '社区线', 60, 29, 13),
    ('HD-03', '长河园区揽收站', '滨江片区', '路芸', '园区线', 60, 27, 10),
    ('HD-04', '钱江世纪城站', '萧山片区', '姚辉', '写字楼线', 60, 24, 14),
    ('HD-05', '北干直营网点', '萧山片区', '郑瑜', '社区线', 60, 42, 18),
    ('HD-06', '萧山机场快运站', '萧山片区', '许茗', '枢纽线', 65, 45, 19),
    ('HD-07', '滨康路揽收站', '滨江片区', '林哲', '园区线', 60, 40, 18),
    ('HD-08', '浦沿社区揽收站', '滨江片区', '沈宁', '社区线', 60, 43, 18),
    ('HD-09', '九堡集散揽收站', '上城片区', '陈舟', '枢纽线', 60, 88, 25),
    ('HD-10', '笕桥直营网点', '上城片区', '罗新', '社区线', 60, 91, 20),
    ('HD-11', '丁兰社区揽收站', '上城片区', '顾平', '社区线', 65, 89, 25),
    ('HD-12', '彭埠电商园站', '上城片区', '田乐', '园区线', 60, 86, 19),
    ('HD-13', '白马湖临时揽收点', '滨江片区', '何青', '临时点', 60, 78, 22),
]


def ensure(db, model, natural_key, **data):
    statement = insert(model).values(**data)
    return db.execute(statement.on_duplicate_key_update(**{natural_key: getattr(model, natural_key)}))


def seed():
    rng = Random(20261121)
    with transaction() as db:
        for account in ACCOUNTS:
            if db.get(User, account) is None:
                ensure(db, User, 'username', username=account, role=account, password_hash=password_hash(DEMO_PASSWORD))
        for code, name, region, lead, route_type, sla, center, spread in STATIONS:
            ensure(db, Station, 'code', code=code, name=name, region=region, lead=lead,
                   route_type=route_type, sla_minutes=sla)
            days = [21] if code == 'HD-13' else [16, 17, 19, 21]
            for day in days:
                business_date = date(2026, 11, day)
                suffix = code.rsplit('-', 1)[1]
                batch_code = f'SCN-11{day}-{suffix}'
                planned_hour = 16 if day in (17, 21) else 10
                count = 8 if len(days) == 1 else 12 + (int(suffix) + day) % 7
                durations = [max(8, center + rng.randint(-spread, spread)) for _ in range(count)]
                if db.get(PickupBatch, batch_code) is not None:
                    continue
                batch = PickupBatch(code=batch_code, station_code=code, business_date=business_date,
                                    shift='afternoon' if planned_hour == 16 else 'morning',
                                    source_name=f'杭州直营网_{business_date:%Y%m%d}_{suffix}.csv', recorded_by='analyst')
                for index, elapsed in enumerate(durations, 1):
                    planned = datetime.combine(business_date, time(planned_hour)) + timedelta(minutes=index * 2)
                    batch.scans.append(PickupScan(parcel_code=f'QY-{business_date:%m%d}-{suffix}-{index:03}',
                                                  planned_at=planned, scanned_at=planned + timedelta(minutes=elapsed),
                                                  elapsed_minutes=elapsed))
                db.add(batch)
    print('Seed committed (existing accounts, station data and batches preserved)')


if __name__ == '__main__':
    seed()
