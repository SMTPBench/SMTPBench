"""Integration tests for SMTPBench using local test mail server"""

import pytest
import subprocess
import mailbox
import os
import re
import time
import shutil


@pytest.fixture(scope="module")
def docker_compose_setup():
    """Set up and tear down Docker Compose services for integration tests"""
    # Clean up any previous test artifacts
    for path in ['test-mail', 'logs']:
        if os.path.exists(path):
            shutil.rmtree(path)
        os.makedirs(path, exist_ok=True)
    
    # Start mail server
    subprocess.run(
        ['docker-compose', '-f', 'docker-compose.test.yml', 'up', '-d', 'mail-server'],
        check=True,
        capture_output=True
    )
    
    # Wait for mail server to be ready
    time.sleep(5)
    
    yield
    
    # Cleanup
    subprocess.run(
        ['docker-compose', '-f', 'docker-compose.test.yml', 'down'],
        check=False,
        capture_output=True
    )


@pytest.mark.integration
def test_smtpbench_sends_emails(docker_compose_setup):
    """Test that SMTPBench successfully sends emails to the test mail server"""
    
    # Run SMTPBench
    result = subprocess.run(
        ['docker-compose', '-f', 'docker-compose.test.yml', 'up', '--build', 'smtpbench'],
        capture_output=True,
        text=True
    )
    
    # Wait for messages to be processed
    time.sleep(5)
    
    # Check that SMTPBench exited successfully
    assert result.returncode == 0, f"SMTPBench failed: {result.stderr}"
    
    # Verify mbox file exists
    mbox_path = 'test-mail/root'
    assert os.path.exists(mbox_path), f"mbox file not found at {mbox_path}"
    
    # Parse mbox file
    mbox = mailbox.mbox(mbox_path)
    message_count = len(mbox)
    
    # Should have at least 10 messages (threads=5, messages=10 in docker-compose)
    expected_messages = 50  # 5 threads * 10 messages
    assert message_count >= expected_messages, \
        f"Expected at least {expected_messages} messages, found {message_count}"
    
    # Validate message content
    smtpbench_messages = 0
    run_uuids = set()
    
    for message in mbox:
        subject = message.get('Subject', '')
        from_addr = message.get('From', '')
        to_addr = message.get('To', '')
        
        # Check if it's from SMTPBench (look for the UUID in brackets)
        uuid_match = re.search(r'\[([a-f0-9\-]+)\]', subject)
        if uuid_match and 'Quick test from thread' in subject:
            smtpbench_messages += 1
            run_uuids.add(uuid_match.group(1))
            
            # Validate from and to addresses
            assert 'loadtest@local.ingest.lets.qa' in from_addr
            assert 'test@local.ingest.lets.qa' in to_addr
    
    assert smtpbench_messages >= expected_messages, \
        f"Expected {expected_messages} SMTPBench messages, found {smtpbench_messages}"
    
    assert len(run_uuids) > 0, "No run UUIDs found in messages"
    
    # Verify logs were created
    assert os.path.exists('logs'), "Logs directory not found"
    log_files = os.listdir('logs')
    assert any('success' in f for f in log_files), "No success log file found"


@pytest.mark.integration
def test_smtpbench_message_format(docker_compose_setup):
    """Test that SMTPBench messages have correct format"""
    
    # Run SMTPBench with minimal messages
    subprocess.run(
        ['docker-compose', '-f', 'docker-compose.test.yml', 'up', '--build', 'smtpbench'],
        capture_output=True
    )
    
    time.sleep(5)
    
    mbox_path = 'test-mail/root'
    mbox = mailbox.mbox(mbox_path)
    
    # Check first message format
    for message in mbox:
        if 'Quick test' in message.get('Subject', ''):
            # Validate headers
            assert message.get('From') is not None
            assert message.get('To') is not None
            assert message.get('Subject') is not None
            
            # Validate custom headers
            assert message.get('X-SMTPBench-Run-UUID') is not None
            assert message.get('X-SMTPBench-Thread-ID') is not None
            assert message.get('X-SMTPBench-Message-ID') is not None
            
            # Validate subject format (contains UUID in brackets)
            subject = message.get('Subject')
            assert 'thread' in subject
            assert 'message' in subject
            assert re.search(r'\[([a-f0-9\-]+)\]', subject) is not None
            
            # Check message body exists
            payload = message.get_payload()
            if isinstance(payload, list):
                body = payload[0].get_payload()
            else:
                body = payload
            assert len(body) > 0
            assert 'SMTPBench Load Testing Tool' in body
            
            break
    else:
        pytest.fail("No SMTPBench messages found")


@pytest.mark.integration
def test_smtpbench_logs_created(docker_compose_setup):
    """Test that SMTPBench creates proper log files"""
    
    # Run SMTPBench
    subprocess.run(
        ['docker-compose', '-f', 'docker-compose.test.yml', 'up', '--build', 'smtpbench'],
        capture_output=True
    )
    
    time.sleep(5)
    
    # Check log directory exists
    assert os.path.exists('logs'), "Logs directory not found"
    
    log_files = os.listdir('logs')
    assert len(log_files) > 0, "No log files created"
    
    # Should have at least a success log
    success_logs = [f for f in log_files if 'success' in f]
    assert len(success_logs) > 0, "No success log file found"
    
    # Validate log file format (should contain JSON)
    success_log_path = os.path.join('logs', success_logs[0])
    with open(success_log_path, 'r') as f:
        first_line = f.readline()
        assert first_line.strip(), "Log file is empty"
        # Should be valid JSON (would raise exception if not)
        import json
        log_entry = json.loads(first_line)
        
        # Validate required fields
        required_fields = [
            'timestamp', 'run_uuid', 'client_hostname', 'status',
            'thread_id', 'message_id', 'duration_seconds'
        ]
        for field in required_fields:
            assert field in log_entry, f"Missing required field: {field}"


if __name__ == '__main__':
    pytest.main([__file__, '-v', '-m', 'integration'])
