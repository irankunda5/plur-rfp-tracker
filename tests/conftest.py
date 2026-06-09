"""Shared test fixtures for plur--rfp-tracker."""

import sys
from pathlib import Path

# Ensure the project root is importable from all test files.
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from lib.storage import OpportunityStore


@pytest.fixture
def store(tmp_path):
    """Create an isolated OpportunityStore backed by a temp SQLite DB."""
    return OpportunityStore(db_path=tmp_path / "test.db")
