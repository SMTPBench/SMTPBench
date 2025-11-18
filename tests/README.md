# SMTPBench Integration Tests

This directory contains integration tests that validate SMTPBench against a real SMTP server.

## Overview

The integration test uses Docker Compose to:
1. Start a local test mail server ([local-test-mail-server](https://github.com/lets-qa/local-test-mail-server))
2. Run SMTPBench to send test emails
3. Validate that emails were received correctly in the mbox file

## Running the Tests

### Quick Start

```bash
./tests/run_integration_test.sh
```

### Manual Testing

You can also run the services manually:

```bash
# Start the mail server
docker compose -f docker-compose.test.yml up -d mail-server

# Wait a few seconds for it to be ready
sleep 5

# Run SMTPBench
docker compose -f docker-compose.test.yml up smtpbench

# Validate results
docker compose -f docker-compose.test.yml up validator

# Cleanup
docker compose -f docker-compose.test.yml down
```

### Custom Test Parameters

You can modify the test parameters in `docker-compose.test.yml`:

```yaml
smtpbench:
  command: >
    recipient=test@local.ingest.lets.qa
    lb_host=mail-server
    port=25
    threads=10           # Change number of threads
    messages=50          # Change number of messages
    use_tls=false
```

## Test Components

### docker-compose.test.yml

Defines three services:
- **mail-server**: Local SMTP server that accepts and stores emails
- **smtpbench**: Runs the load test against the mail server
- **validator**: Python script that validates the mbox file

### validate_mbox.py

Python script that:
- Checks if the mbox file exists
- Counts messages received
- Validates message format
- Extracts run UUIDs
- Reports success/failure

### run_integration_test.sh

Bash script that orchestrates the full test:
- Cleans up previous test artifacts
- Starts services in correct order
- Waits for processing
- Runs validation
- Reports results
- Cleans up containers

## Viewing Results

After running the test:

- **logs/**: Contains SMTPBench JSON logs (success, fail, retry)
- **test-mail/root**: Contains the mbox file with received emails

You can inspect the mbox file manually:

```bash
# View raw mbox file
cat test-mail/root

# Or use Python to parse it
python3 -c "
import mailbox
mbox = mailbox.mbox('test-mail/root')
for i, msg in enumerate(mbox):
    print(f'Message {i+1}:')
    print(f'  From: {msg[\"From\"]}')
    print(f'  Subject: {msg[\"Subject\"]}')
    print()
"
```

## Troubleshooting

### Mail server not starting

Check Docker logs:
```bash
docker compose -f docker-compose.test.yml logs mail-server
```

### No messages received

1. Check if SMTPBench connected successfully:
```bash
docker compose -f docker-compose.test.yml logs smtpbench
```

2. Verify network connectivity:
```bash
docker compose -f docker-compose.test.yml exec smtpbench ping mail-server
```

### Validation fails

Check the mbox file directly:
```bash
ls -lh test-mail/
cat test-mail/root
```

## CI/CD Integration

This test can be integrated into CI/CD pipelines:

```bash
# Run test and capture exit code
./tests/run_integration_test.sh
EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    echo "Tests passed"
else
    echo "Tests failed"
    exit 1
fi
```
