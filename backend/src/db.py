import os
from contextlib import contextmanager

from redis import Redis
from sqlalchemy import URL, create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


engine = create_engine(
    URL.create(
        'mysql+pymysql',
        username=os.getenv('MYSQL_USER', 'pickup'),
        password=os.getenv('MYSQL_PASSWORD', 'pickup-local-1044'),
        host=os.getenv('MYSQL_HOST', '127.0.0.1'),
        port=int(os.getenv('MYSQL_PORT', '17743')) if 'MYSQL_HOST' not in os.environ else 3306,
        database=os.getenv('MYSQL_DATABASE', 'pickup'),
        query={'charset': 'utf8mb4'},
    ),
    pool_pre_ping=True,
    isolation_level='READ COMMITTED',
)
Session = sessionmaker(engine, expire_on_commit=False)
cache = Redis.from_url(os.getenv('REDIS_URL', 'redis://127.0.0.1:6379/0'), socket_timeout=2)


@contextmanager
def transaction():
    with Session.begin() as db:
        yield db


def session():
    with Session() as db:
        yield db
