"""Pytest configuration and fixtures"""

import os
import sys

import pytest

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


@pytest.fixture(autouse=True)
def reset_globals():
    """Reset the mutable CLI counters and run state (success/fail/retry counts,
    stop flag, and mx_hosts) before and after each test."""
    from smtpbench import cli

    # Reset global counters
    cli.success_count = 0
    cli.fail_count = 0
    cli.retry_count = 0
    cli.stop_requested = False
    cli.mx_hosts = []
    cli.attachment_plan = None
    cli.auth_username = None
    cli.auth_password = None

    yield

    # Cleanup after test
    cli.success_count = 0
    cli.fail_count = 0
    cli.retry_count = 0
    cli.stop_requested = False
    cli.mx_hosts = []
    cli.attachment_plan = None
    cli.auth_username = None
    cli.auth_password = None


@pytest.fixture
def mock_logger():
    """Provide a mock logger for testing"""
    from unittest.mock import Mock

    return Mock()
