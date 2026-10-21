import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.api.deps import get_db
from app.config import get_settings
from app.main import app
from app.models import Base

HEADERS = {"X-Requested-With": "ChessReviewLab"}


def _test_url():
    url = make_url(get_settings().database_url)
    return url, url.set(database=f"{url.database}_test")


@pytest.fixture(scope="session")
def test_engine():
    admin_url, test_url = _test_url()
    admin = create_engine(admin_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": test_url.database}
        )
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{test_url.database}"'))
    admin.dispose()
    engine = create_engine(test_url)
    with engine.begin() as conn:  # start from a clean slate, whatever an earlier run left
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def _clean_db(request, test_engine):
    uses_db = {"client", "make_client", "db_factory"} & set(request.fixturenames)
    if not uses_db:
        yield
        return
    with test_engine.begin() as conn:
        tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    yield


@pytest.fixture
def db_factory(test_engine):
    return sessionmaker(bind=test_engine, expire_on_commit=False)


@pytest.fixture
def make_client(test_engine, db_factory):
    """Factory: every client has its own cookie jar, i.e. its own anonymous user."""
    factory = db_factory

    def override():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override
    clients: list[TestClient] = []

    def make(start_session: bool = True) -> TestClient:
        c = TestClient(app, headers=HEADERS)
        if start_session:
            assert c.post("/api/session").status_code == 200
        clients.append(c)
        return c

    yield make
    for c in clients:
        c.close()
    app.dependency_overrides.clear()


@pytest.fixture
def client(make_client):
    return make_client()
