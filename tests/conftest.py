"""Pytest configuration and shared fixtures for SchemaGuard test suite."""

import pytest
from schemaguard.core.storage import DuckDBStorageManager


@pytest.fixture
def in_memory_storage() -> DuckDBStorageManager:
    """Provide a fresh in-memory DuckDBStorageManager instance for tests."""
    return DuckDBStorageManager(db_path=":memory:")
