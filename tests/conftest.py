"""
Pytest configuration for LLM Gateway tests.
"""

import os
import pytest
import asyncio


@pytest.fixture(scope="session")
def event_loop():
    """Create an event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def gateway_url():
    """Gateway URL for tests."""
    return os.environ.get("GATEWAY_URL", "http://localhost:4000")


@pytest.fixture
def master_key():
    """Master key for tests."""
    return os.environ.get("LITELLM_MASTER_KEY", "sk-master-key-change-me")


@pytest.fixture
def database_url():
    """Database URL for tests."""
    return os.environ.get("DATABASE_URL", "postgresql://litellm:litellm@localhost:5432/litellm")
