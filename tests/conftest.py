import pytest

from skibasar import main
from skibasar.db import init_db, make_engine
from skibasar.models import Event


def _init_db_numbers_from_zero(engine):
    factory = init_db(engine)
    with factory() as s:
        s.get(Event, 1).private_number_start = 0
        s.commit()
    return factory


@pytest.fixture(autouse=True)
def private_numbers_from_zero(monkeypatch):
    """Most tests were written when private numbers started at 0 by default; keep that for them.

    Tests of the real default (1) remove this patch with ``monkeypatch.undo()``.
    """
    monkeypatch.setattr(main, "init_db", _init_db_numbers_from_zero)


@pytest.fixture
def session(tmp_path):
    factory = _init_db_numbers_from_zero(make_engine(tmp_path / "test.db"))
    with factory() as s:
        yield s
