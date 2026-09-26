"""
Pytest configuration for LLM Gateway evals.
"""

import os
import pytest


def pytest_addoption(parser):
    """Add custom command line options."""
    parser.addoption(
        "--eval-mode",
        action="store_true",
        default=False,
        help="Run in eval mode (use gateway for completions)",
    )
    parser.addoption(
        "--gateway-url",
        action="store",
        default=os.environ.get("GATEWAY_URL", "http://localhost:4000"),
        help="Gateway URL for evals",
    )
    parser.addoption(
        "--eval-model",
        action="store",
        default=os.environ.get("EVAL_MODEL", "fake/echo"),
        help="Model to use for evals",
    )
    parser.addoption(
        "--threshold-file",
        action="store",
        default="evals/thresholds.yaml",
        help="Path to threshold configuration file",
    )


@pytest.fixture
def gateway_url(request):
    """Get the gateway URL."""
    return request.config.getoption("--gateway-url")


@pytest.fixture
def eval_model(request):
    """Get the eval model."""
    return request.config.getoption("--eval-model")


@pytest.fixture
def eval_mode(request):
    """Check if running in eval mode."""
    return request.config.getoption("--eval-mode")
