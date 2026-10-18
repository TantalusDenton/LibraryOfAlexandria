import os
import tempfile
from pathlib import Path

ROOT = Path(tempfile.mkdtemp(prefix="alexandria-tests-"))
os.environ.update(
    DATABASE_URL=f"sqlite:///{ROOT}/test.db",
    CHECKPOINT_URL=f"sqlite:///{ROOT}/graph.db",
    DATA_DIR=str(ROOT),
    AI_MODE="offline",
    JWT_SECRET="test-session-secret-" * 3,
)
import pytest  # noqa: E402

from app import models  # noqa: E402,F401
from app.db import Base, SessionLocal, engine  # noqa: E402


@pytest.fixture(autouse=True)
def clean_database():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture
def db():
    with SessionLocal() as session:
        yield session
