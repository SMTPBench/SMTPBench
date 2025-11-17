"""Pytest configuration and fixtures"""

import pytest
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


@pytest.fixture(autouse=True)
def reset_globals():
    """Reset global variables before each test"""
    from smtpbench import cli
    
    # Reset global counters
    cli.success_count = 0
    cli.fail_count = 0
    cli.retry_count = 0
    cli.stop_requested = False
    cli.mx_hosts = []
    
    yield
    
    # Cleanup after test
    cli.success_count = 0
    cli.fail_count = 0
    cli.retry_count = 0
    cli.stop_requested = False
    cli.mx_hosts = []


@pytest.fixture
def mock_logger():
    """Provide a mock logger for testing"""
    from unittest.mock import Mock
    return Mock()
