"""Shared pytest fixtures: temporary DB, FastAPI client, bootstrapped engine."""
import os
import sys
import shutil
import tempfile
import pytest
from pathlib import Path

# Make the project root importable
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Disable the background engine thread for all tests; tests trigger rounds manually.
os.environ["EMERGENCE_TEST_MODE"] = "1"


@pytest.fixture(scope="function")
def tmp_db(monkeypatch):
    """Redirect the DB to a fresh temp file for each test."""
    tmpdir = tempfile.mkdtemp(prefix="emerge-test-")
    db_path = Path(tmpdir) / "test.db"
    # Import here so we can patch the module-level constant
    from engine import db
    monkeypatch.setattr(db, "DB_PATH", db_path)
    # Re-seed
    db.init_db()
    from engine import world, agents as agents_mod, tools
    # Force re-bootstrap by clearing the seeded flag
    db.set_world_state("landmarks_seeded", False)
    db.set_world_state("agents_seeded", False)
    world.bootstrap()
    agents_mod.bootstrap()
    tools.bootstrap()
    yield db_path
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture(scope="function")
def client(tmp_db):
    """FastAPI TestClient bound to the temp DB."""
    # Ensure the app's startup hooks are run
    from server import app
    from fastapi.testclient import TestClient
    with TestClient(app) as c:
        yield c
