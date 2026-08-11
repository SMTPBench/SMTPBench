"""Pytest configuration and fixtures"""

import os
import sys

import pytest

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


@pytest.fixture(autouse=True)
def reset_globals():
    """Reset the mutable CLI counters and run state (success/fail/retry counts,
    stop flag, mx_hosts, and debug state) before and after each test."""
    from smtpbench import cli

    # Reset global counters
    cli.success_count = 0
    cli.fail_count = 0
    cli.retry_count = 0
    cli.stop_requested = False
    cli.mx_hosts = []
    cli.attachment_plan = None
    cli.body_plan = None
    cli.recipient_list = None
    cli.from_list = None
    cli.journal_list = None
    cli.offline_mode = False
    cli.eml_out_dir = None
    cli.auth_username = None
    cli.auth_password = None
    cli.rate_limiter = None
    cli.latency_samples = []
    cli.per_mx_stats = {}
    # Debug state gates the `if debug_enabled:` branches in the send path and
    # banner check. Tests that turn it on must not leak it into later tests.
    cli.debug_enabled = False
    cli.debug_logger = None

    yield

    # Cleanup after test
    cli.success_count = 0
    cli.fail_count = 0
    cli.retry_count = 0
    cli.stop_requested = False
    cli.mx_hosts = []
    cli.attachment_plan = None
    cli.body_plan = None
    cli.recipient_list = None
    cli.from_list = None
    cli.journal_list = None
    cli.offline_mode = False
    cli.eml_out_dir = None
    cli.auth_username = None
    cli.auth_password = None
    cli.rate_limiter = None
    cli.latency_samples = []
    cli.per_mx_stats = {}
    # Debug state gates the `if debug_enabled:` branches in the send path and
    # banner check. Tests that turn it on must not leak it into later tests.
    cli.debug_enabled = False
    cli.debug_logger = None


@pytest.fixture
def mock_logger():
    """Provide a mock logger for testing"""
    from unittest.mock import Mock

    return Mock()
