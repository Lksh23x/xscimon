import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from xscimon.main import app
from xscimon.database import get_session
from xscimon.adapters.mock import MockXAPIAdapter, MockLLMAdapter, MockEmailAdapter
from xscimon.adapters import get_x_adapter, get_llm_adapter, get_email_adapter


@pytest.fixture(name="session")
def session_fixture():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture(name="client")
def client_fixture(session: Session):
    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_x_adapter] = lambda: MockXAPIAdapter()
    app.dependency_overrides[get_llm_adapter] = lambda: MockLLMAdapter()
    app.dependency_overrides[get_email_adapter] = lambda: MockEmailAdapter()

    # Suppress DB init during tests
    with patch("xscimon.main.init_db"):
        with TestClient(app, raise_server_exceptions=True) as client:
            yield client

    app.dependency_overrides.clear()


@pytest.fixture
def mock_email():
    return MockEmailAdapter()
