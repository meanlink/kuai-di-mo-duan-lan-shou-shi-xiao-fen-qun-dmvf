import pytest

from src import review, worker
from src.db import Base

from .support import engine, TestSession, tx


@pytest.fixture(autouse=True)
def schema(monkeypatch):
    monkeypatch.setattr(review, 'transaction', tx)
    monkeypatch.setattr(worker, 'transaction', tx)
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture
def db():
    with TestSession() as session:
        yield session
