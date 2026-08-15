"""Pytest configuration and fixtures"""

import logging
import os
import sys

import pytest

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


# Captured on first use, while it still holds its import-time value. run_uuid
# seeds send_email's per-message RNG, so a test that pins it for determinism
# would otherwise change which addresses and attachments every later test draws.
_RUN_METADATA = {}


@pytest.fixture(autouse=True)
def reset_globals():
    """Reset the mutable CLI counters and run state (success/fail/retry counts,
    stop flag, mx_hosts, run UUID, and debug state) before and after each test."""
    from smtpbench import cli

    _RUN_METADATA.setdefault("run_uuid", cli.run_uuid)

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
    # Journal state adds a second envelope recipient in send_email.
    cli.journal_enabled = False
    cli.journal_address = None
    cli.run_uuid = _RUN_METADATA["run_uuid"]

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
    # Journal state adds a second envelope recipient in send_email.
    cli.journal_enabled = False
    cli.journal_address = None
    cli.run_uuid = _RUN_METADATA["run_uuid"]


@pytest.fixture(autouse=True)
def reset_file_loggers():
    """Detach the file handlers setup_logging() attaches.

    setup_logging() looks up four fixed logger names via logging.getLogger()
    and unconditionally addHandler()s a FileHandler to each. Those loggers
    outlive the call, so tests that run main() would stack up handlers and keep
    writing into earlier tests' (already-deleted) temp directories.
    """
    names = ("success", "fail", "retry", "debug")

    def detach():
        for name in names:
            logger = logging.getLogger(name)
            for handler in list(logger.handlers):
                logger.removeHandler(handler)
                handler.close()

    detach()
    yield
    detach()


@pytest.fixture
def mock_logger():
    """Provide a mock logger for testing"""
    from unittest.mock import Mock

    return Mock()
