"""Shared pytest configuration.

Two test layers are provided:

* pure unit tests (no database) — always run;
* integration tests marked ``integration`` that require a migrated PostGIS
  database with the demo dataset. Enable them with::

      PETA_TEST_DATABASE_URL=postgresql://peta:peta_secret@127.0.0.1:55432/peta pytest

The environment is configured *before* importing the application because
``app.main`` reads settings at import time.
"""

from __future__ import annotations

import os

import pytest

TEST_DATABASE_URL = os.getenv("PETA_TEST_DATABASE_URL")

# Keep unit tests hermetic: no external geocoders, no API key, generous limits.
os.environ["API_KEYS"] = ""
os.environ["PHOTON_URL"] = ""
os.environ["NOMINATIM_URL"] = ""
os.environ["RATE_LIMIT_PER_MINUTE"] = "10000"
os.environ.setdefault(
    "DATABASE_URL",
    TEST_DATABASE_URL or "postgresql://peta:peta_secret@127.0.0.1:55432/peta",
)

from app.config import get_settings  # noqa: E402

get_settings.cache_clear()

from app.main import app  # noqa: E402


@pytest.fixture()
def client():
    """Application client without lifespan: services are mocked per test."""
    from fastapi.testclient import TestClient

    return TestClient(app)


@pytest.fixture(scope="session")
def test_database_url() -> str:
    if not TEST_DATABASE_URL:
        pytest.skip("PETA_TEST_DATABASE_URL is not set")
    return TEST_DATABASE_URL


@pytest.fixture(scope="session")
def live_client():
    """Client with a real pool/lifespan against the demo PostGIS database."""
    if not TEST_DATABASE_URL:
        pytest.skip("PETA_TEST_DATABASE_URL is not set")

    from fastapi.testclient import TestClient

    with TestClient(app) as test_client:
        yield test_client
