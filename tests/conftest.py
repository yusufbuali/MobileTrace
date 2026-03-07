"""Shared fixtures for MobileTrace tests."""
import pytest
from app import create_app
from app.database import init_db, close_db


@pytest.fixture(scope="function")
def app(tmp_path):
    """App instance with isolated temp DB."""
    db_path = str(tmp_path / "test.db")
    _app = create_app(testing=True)
    _app.config["MT_CONFIG"]["server"]["database_path"] = db_path
    _app.config["MT_CONFIG"]["server"]["cases_dir"] = str(tmp_path / "cases")
    init_db(db_path)
    yield _app
    close_db()


@pytest.fixture(scope="function")
def client(app):
    with app.test_client() as c:
        yield c
