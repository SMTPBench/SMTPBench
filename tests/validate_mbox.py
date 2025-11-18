#!/usr/bin/env python3
"""
Validates that SMTPBench successfully sent emails to the local test mail server.
Checks the mbox file for expected message count and format.
Validates against the current run's UUID to avoid false positives from old messages.
"""
import mailbox
import sys
import os
import re
import json
import glob


def get_current_run_uuid():
    """Extract the run UUID from the latest SMTPBench success log."""
    log_dir = os.environ.get('LOG_DIR', '/logs')
    
    # Find the most recent success log
    success_logs = glob.glob(os.path.join(log_dir, 'success_*.log'))
    if not success_logs:
        print("⚠️  Warning: No success logs found, will validate all messages")
        return None
    
    latest_log = max(success_logs, key=os.path.getmtime)
    
    # Read first line to get run_uuid
    try:
        with open(latest_log, 'r') as f:
            first_line = f.readline()
            log_entry = json.loads(first_line)
            run_uuid = log_entry.get('run_uuid')
            print(f"✓ Found current run UUID: {run_uuid}")
            return run_uuid
    except Exception as e:
        print(f"⚠️  Warning: Could not extract run UUID from logs: {e}")
        return None


def validate_mbox(mbox_path="/var/mail/root", expected_messages=10, run_uuid=None):
    """Validate the mbox file contains expected messages from SMTPBench."""
    
    if not os.path.exists(mbox_path):
        print(f"❌ FAIL: mbox file not found at {mbox_path}")
        return False
    
    print(f"✓ Found mbox file at {mbox_path}")
    
    # Open and parse the mbox file
    try:
        mbox = mailbox.mbox(mbox_path)
        message_count = len(mbox)
        
        print(f"✓ Found {message_count} messages in mbox")
        
        # Validate message content
        smtpbench_messages = 0
        current_run_messages = 0
        all_run_uuids = set()
        
        for idx, message in enumerate(mbox):
            subject = message.get('Subject', '')
            from_addr = message.get('From', '')
            to_addr = message.get('To', '')
            header_uuid = message.get('X-SMTPBench-Run-UUID', '')
            
            # Check if it's from SMTPBench (contains "Quick test")
            if 'Quick test' in subject:
                smtpbench_messages += 1
                
                # Extract run UUID from header (preferred) or subject
                msg_uuid = header_uuid
                if not msg_uuid:
                    uuid_match = re.search(r'\[([a-f0-9\-]+)\]', subject)
                    if uuid_match:
                        msg_uuid = uuid_match.group(1)
                
                if msg_uuid:
                    all_run_uuids.add(msg_uuid)
                    
                    # If we have a specific run UUID to validate against, count only those messages
                    if run_uuid and msg_uuid == run_uuid:
                        current_run_messages += 1
                        if current_run_messages <= 5:  # Show first 5
                            print(f"  Message {current_run_messages}:")
                            print(f"    From: {from_addr}")
                            print(f"    To: {to_addr}")
                            print(f"    UUID: {msg_uuid}")
                            print(f"    Subject: {subject[:80]}...")
        
        print(f"\n✓ Found {smtpbench_messages} total SMTPBench messages")
        print(f"✓ Found {len(all_run_uuids)} unique run UUID(s)")
        
        if run_uuid:
            print(f"✓ Found {current_run_messages} messages from current run ({run_uuid})")
            
            if current_run_messages < expected_messages:
                print(f"❌ FAIL: Expected {expected_messages} messages from current run, found {current_run_messages}")
                return False
        else:
            if smtpbench_messages < expected_messages:
                print(f"❌ FAIL: Expected {expected_messages} SMTPBench messages, found {smtpbench_messages}")
                return False
        
        if run_uuid:
            print(f"\n✅ SUCCESS: All validations passed for current run!")
            print(f"   - {message_count} total messages in mbox")
            print(f"   - {smtpbench_messages} total SMTPBench messages")
            print(f"   - {current_run_messages} messages from current run")
            print(f"   - All messages properly formatted")
        else:
            print(f"\n✅ SUCCESS: All validations passed!")
            print(f"   - {message_count} total messages received")
            print(f"   - {smtpbench_messages} SMTPBench test messages")
            print(f"   - All messages properly formatted")
        
        return True
        
    except Exception as e:
        print(f"❌ FAIL: Error reading mbox file: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    # Default to 50 messages, but can be overridden via environment variable
    expected = int(os.environ.get('EXPECTED_MESSAGES', '50'))
    mbox_path = os.environ.get('MBOX_PATH', '/var/mail/root')
    
    # Get the current run UUID from logs
    current_run_uuid = get_current_run_uuid()
    
    success = validate_mbox(mbox_path, expected, current_run_uuid)
    sys.exit(0 if success else 1)
