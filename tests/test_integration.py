"""Integration tests for SMTPBench using local test mail server"""

import glob
import json
import mailbox
import os
import re
import shutil
import subprocess
import time

import pytest


def get_current_run_uuid(log_dir="logs"):
    """Return the run UUID from the most recent success log, or None if unavailable.

    Mirrors validate_mbox.get_current_run_uuid but resolves the pytest-side log
    directory (./logs) and stays quiet so callers can assert on the result.
    """
    success_logs = glob.glob(os.path.join(log_dir, "success_*.log"))
    if not success_logs:
        return None
    latest_log = max(success_logs, key=os.path.getmtime)
    try:
        with open(latest_log) as f:
            return json.loads(f.readline()).get("run_uuid")
    except (OSError, ValueError):
        return None


def fix_mbox_permissions(mbox_path="test-mail/root"):
    """Fix permissions on mbox file created by Docker"""
    if not os.path.exists(mbox_path) or os.path.getsize(mbox_path) == 0:
        return

    # Try docker exec first (if mail server container is running)
    subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            "docker-compose.test.yml",
            "exec",
            "-T",
            "mail-server",
            "chmod",
            "644",
            "/var/mail/root",
        ],
        capture_output=True,
    )

    # If docker exec didn't work, file should already be readable via the volume mount
    # Just verify we can read it
    try:
        with open(mbox_path) as f:
            f.read(1)
    except PermissionError:
        # Last resort: try chmod without sudo (will fail in CI but documents the issue)
        subprocess.run(["chmod", "644", mbox_path], check=False, capture_output=True)


@pytest.fixture(scope="module")
def docker_compose_setup():
    """Set up and tear down Docker Compose services for integration tests"""
    # Clean up any previous test artifacts
    for path in ["test-mail", "logs"]:
        if os.path.exists(path):
            shutil.rmtree(path)
        os.makedirs(path, exist_ok=True)

    # Start mail server
    subprocess.run(
        ["docker", "compose", "-f", "docker-compose.test.yml", "up", "-d", "mail-server"],
        check=True,
        capture_output=True,
    )

    # Wait for mail server to be ready
    time.sleep(5)

    yield

    # Fix permissions before cleanup so artifacts can be uploaded
    fix_mbox_permissions()

    # Cleanup
    subprocess.run(
        ["docker", "compose", "-f", "docker-compose.test.yml", "down"],
        check=False,
        capture_output=True,
    )


@pytest.mark.integration
def test_smtpbench_sends_emails(docker_compose_setup):
    """Test that SMTPBench successfully sends emails to the test mail server"""

    # Run SMTPBench
    result = subprocess.run(
        ["docker", "compose", "-f", "docker-compose.test.yml", "up", "--build", "smtpbench"],
        capture_output=True,
        text=True,
    )

    # Wait for messages to be processed
    time.sleep(5)

    # Check that SMTPBench exited successfully
    assert result.returncode == 0, f"SMTPBench failed: {result.stderr}"

    # Verify mbox file exists
    mbox_path = "test-mail/root"
    assert os.path.exists(mbox_path), f"mbox file not found at {mbox_path}"

    # Fix permissions on mbox file
    fix_mbox_permissions(mbox_path)

    # Parse mbox file
    mbox = mailbox.mbox(mbox_path)
    message_count = len(mbox)

    # Should have at least 10 messages (threads=5, messages=10 in docker-compose)
    expected_messages = 50  # 5 threads * 10 messages
    assert message_count >= expected_messages, (
        f"Expected at least {expected_messages} messages, found {message_count}"
    )

    # Scope validation to the current invocation's run UUID so stale messages
    # from earlier runs in the shared mbox can't satisfy the assertions.
    run_uuid = get_current_run_uuid()
    assert run_uuid, "Could not determine current run UUID from success logs"

    # Validate message content
    smtpbench_messages = 0

    for message in mbox:
        subject = message.get("Subject", "")
        from_addr = message.get("From", "")
        to_addr = message.get("To", "")
        header_uuid = message.get("X-SMTPBench-Run-UUID", "")

        if "Quick test from thread" not in subject:
            continue

        # Prefer the header UUID; fall back to the one embedded in the subject.
        msg_uuid = header_uuid
        if not msg_uuid:
            uuid_match = re.search(r"\[([a-f0-9\-]+)\]", subject)
            msg_uuid = uuid_match.group(1) if uuid_match else ""

        if msg_uuid == run_uuid:
            smtpbench_messages += 1

            # Validate from and to addresses
            assert "loadtest@local.ingest.lets.qa" in from_addr
            assert "test@local.ingest.lets.qa" in to_addr

    assert smtpbench_messages >= expected_messages, (
        f"Expected {expected_messages} messages from run {run_uuid}, found {smtpbench_messages}"
    )

    # Verify logs were created
    assert os.path.exists("logs"), "Logs directory not found"
    log_files = os.listdir("logs")
    assert any("success" in f for f in log_files), "No success log file found"


@pytest.mark.integration
def test_smtpbench_message_format(docker_compose_setup):
    """Test that SMTPBench messages have correct format"""

    # Run SMTPBench with minimal messages
    result = subprocess.run(
        ["docker", "compose", "-f", "docker-compose.test.yml", "up", "--build", "smtpbench"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"SMTPBench failed: {result.stderr}"

    time.sleep(5)

    # Scope to the current invocation's run UUID so a stale message can't be
    # the one we inspect.
    run_uuid = get_current_run_uuid()
    assert run_uuid, "Could not determine current run UUID from success logs"

    mbox_path = "test-mail/root"
    # Fix permissions on mbox file
    fix_mbox_permissions(mbox_path)
    mbox = mailbox.mbox(mbox_path)

    # Check the current run's message format
    for message in mbox:
        if message.get("X-SMTPBench-Run-UUID") == run_uuid:
            # Validate headers
            assert message.get("From") is not None
            assert message.get("To") is not None
            assert message.get("Subject") is not None

            # Validate custom headers
            assert message.get("X-SMTPBench-Thread-ID") is not None
            assert message.get("X-SMTPBench-Message-ID") is not None

            # Validate subject format (contains UUID in brackets)
            subject = message.get("Subject")
            assert "thread" in subject
            assert "message" in subject
            assert re.search(r"\[([a-f0-9\-]+)\]", subject) is not None

            # Check message body exists
            payload = message.get_payload()
            if isinstance(payload, list):
                body = payload[0].get_payload()
            else:
                body = payload
            assert len(body) > 0
            assert "SMTPBench Load Testing Tool" in body

            break
    else:
        pytest.fail(f"No messages found for current run {run_uuid}")


@pytest.mark.integration
def test_smtpbench_logs_created(docker_compose_setup):
    """Test that SMTPBench creates proper log files"""

    # Run SMTPBench
    result = subprocess.run(
        ["docker", "compose", "-f", "docker-compose.test.yml", "up", "--build", "smtpbench"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"SMTPBench failed: {result.stderr}"

    time.sleep(5)

    # Check log directory exists
    assert os.path.exists("logs"), "Logs directory not found"

    # Scope to the log file for this invocation's run UUID; the log filename
    # embeds the run UUID (success_TIMESTAMP_UUID.log).
    run_uuid = get_current_run_uuid()
    assert run_uuid, "Could not determine current run UUID from success logs"

    success_logs = glob.glob(os.path.join("logs", f"success_*_{run_uuid}.log"))
    assert success_logs, f"No success log file found for current run {run_uuid}"

    # Validate log file format (should contain JSON)
    success_log_path = success_logs[0]
    with open(success_log_path) as f:
        first_line = f.readline()
        assert first_line.strip(), "Log file is empty"
        # Should be valid JSON (would raise exception if not)
        log_entry = json.loads(first_line)

        # Validate required fields
        required_fields = [
            "timestamp",
            "run_uuid",
            "client_hostname",
            "status",
            "thread_id",
            "message_id",
            "duration_seconds",
        ]
        for field in required_fields:
            assert field in log_entry, f"Missing required field: {field}"

        # The log entry's run_uuid must match the current run.
        assert log_entry["run_uuid"] == run_uuid


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "integration"])
