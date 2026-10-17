import pytest

from skibasar.db import init_db, make_engine


@pytest.fixture
def session(tmp_path):
    factory = init_db(make_engine(tmp_path / "test.db"))
    with factory() as s:
        yield s
