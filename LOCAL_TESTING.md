# Local Testing Guide

This guide shows you how to set up a complete local testing environment with SMTPBench and a local SMTP server.

## Overview

You'll set up:
1. A Python virtual environment
2. SMTPBench installed via pip
3. A local SMTP test server in Docker
4. Send test emails and verify delivery

**Time required**: ~5 minutes

## Prerequisites

- Python 3.8 or higher
- Docker installed and running
- Basic terminal knowledge

## Step 1: Set Up Python Virtual Environment

Create a clean Python environment for testing:

```bash
# Create a directory for testing
mkdir ~/smtpbench-test
cd ~/smtpbench-test

# Create virtual environment
python3 -m venv venv

# Activate it
# On macOS/Linux:
source venv/bin/activate

# On Windows:
# venv\Scripts\activate

# Verify activation (you should see (venv) in your prompt)
which python
```

## Step 2: Install SMTPBench

Install SMTPBench from PyPI:

```bash
pip install smtpbench

# Verify installation
smtpbench --version
smtpbench --help
```

You should see version 1.1.0 or higher.

## Step 3: Set Up Local Mail Server

Pull and run the local test mail server:

```bash
# Pull the mail server image
docker pull ghcr.io/lets-qa/local-test-mail-server:main

# Create a directory for mail storage
mkdir -p ~/mail

# Run the mail server with host networking
docker run -d \
  --name test-mail-server \
  --network host \
  -v ~/mail:/var/mail \
  ghcr.io/lets-qa/local-test-mail-server:main
```

### What This Does

- **`--network host`**: Uses your computer's network directly (mail server on localhost:25)
- **`-v ~/mail:/var/mail`**: Mounts your local `~/mail` directory to store received emails
- **Port 25**: Standard SMTP port (may require sudo/admin on some systems)

### Alternative: Using Port Mapping

If port 25 is already in use or requires admin privileges:

```bash
docker run -d \
  --name test-mail-server \
  -p 2525:25 \
  -v ~/mail:/var/mail \
  ghcr.io/lets-qa/local-test-mail-server:main
```

Then use `port=2525` in SMTPBench commands below.

## Step 4: Verify Mail Server is Running

```bash
# Check container status
docker ps | grep test-mail-server

# Check logs
docker logs test-mail-server

# You should see: "postfix/master... daemon started"
```

## Step 5: Send Test Emails with SMTPBench

Now let's spam away! 🚀

### Basic Test (10 messages, 1 thread)

```bash
smtpbench \
  recipient=test@local.ingest.lets.qa \
  lb_host=localhost \
  port=25 \
  from_address=loadtest@local.ingest.lets.qa \
  threads=1 \
  messages=10 \
  use_tls=false
```

### Medium Load (100 messages, 5 threads)

```bash
smtpbench \
  recipient=test@local.ingest.lets.qa \
  lb_host=localhost \
  port=25 \
  from_address=loadtest@local.ingest.lets.qa \
  threads=5 \
  messages=100 \
  use_tls=false
```

### Heavy Load (1000 messages, 10 threads)

```bash
smtpbench \
  recipient=test@local.ingest.lets.qa \
  lb_host=localhost \
  port=25 \
  from_address=loadtest@local.ingest.lets.qa \
  threads=10 \
  messages=1000 \
  use_tls=false
```

### Extreme Load (10,000 messages!)

```bash
smtpbench \
  recipient=test@local.ingest.lets.qa \
  lb_host=localhost \
  port=25 \
  from_address=loadtest@local.ingest.lets.qa \
  threads=20 \
  messages=10000 \
  use_tls=false
```

## Step 6: Verify Email Delivery

Check that emails were delivered to the mbox file:

```bash
# Count messages in the mailbox
grep -c "^From " ~/mail/root

# View first few message headers
head -50 ~/mail/root

# View specific headers
grep "^Subject:" ~/mail/root | head -10
grep "^X-SMTPBench-Run-UUID:" ~/mail/root | head -5

# Check file size
ls -lh ~/mail/root
```

### Expected Results

You should see:
- One line per message from `grep -c "^From "`
- Subject lines showing thread and message numbers
- Unique Run UUID for each test run
- Growing file size with each test

## Step 7: View Logs

SMTPBench creates detailed JSON logs:

```bash
# List log files
ls -lh logs/

# View success log (pretty print)
cat logs/*_success.log | head -20

# Count successful sends
wc -l logs/*_success.log

# View any failures
cat logs/*_failure.log 2>/dev/null || echo "No failures!"
```

## Performance Testing Examples

### Test 1: Measure Throughput

```bash
time smtpbench \
  recipient=test@local.ingest.lets.qa \
  lb_host=localhost \
  port=25 \
  from_address=loadtest@local.ingest.lets.qa \
  threads=10 \
  messages=1000 \
  use_tls=false
```

### Test 2: Stress Test

Run multiple times in a loop:

```bash
for i in {1..5}; do
  echo "Run $i of 5"
  smtpbench \
    recipient=test@local.ingest.lets.qa \
    lb_host=localhost \
    port=25 \
    from_address=loadtest@local.ingest.lets.qa \
    threads=5 \
    messages=100 \
    use_tls=false
  sleep 2
done
```

### Test 3: Ramp Up Load

Gradually increase threads:

```bash
for threads in 1 5 10 20; do
  echo "Testing with $threads threads"
  smtpbench \
    recipient=test@local.ingest.lets.qa \
    lb_host=localhost \
    port=25 \
    from_address=loadtest@local.ingest.lets.qa \
    threads=$threads \
    messages=100 \
    use_tls=false
  echo "---"
  sleep 5
done
```

## Cleanup

When you're done testing:

```bash
# Stop and remove the mail server
docker stop test-mail-server
docker rm test-mail-server

# Optional: Remove mail files
rm -rf ~/mail

# Optional: Remove logs
rm -rf logs/

# Deactivate virtual environment
deactivate
```

## Troubleshooting

### "Connection refused" Error

**Problem**: Can't connect to localhost:25

**Solutions**:
1. Check if mail server is running: `docker ps | grep test-mail-server`
2. Check logs: `docker logs test-mail-server`
3. Try port 2525 instead (use `-p 2525:25` when starting Docker)

### "Permission denied" on Port 25

**Problem**: Port 25 requires root/admin access

**Solution**: Use an alternative port:

```bash
# Start mail server on port 2525
docker run -d \
  --name test-mail-server \
  -p 2525:25 \
  -v ~/mail:/var/mail \
  ghcr.io/lets-qa/local-test-mail-server:main

# Use port 2525 in SMTPBench
smtpbench ... port=2525 ...
```

### "No space left on device"

**Problem**: Large mbox file filling disk

**Solution**: Clean up or increase disk space:

```bash
# Check mbox size
du -h ~/mail/root

# Remove old mail
rm ~/mail/root

# Restart mail server to create fresh mbox
docker restart test-mail-server
```

### Mail Not Appearing in ~/mail/root

**Problem**: Mbox file not being created

**Solution**:
1. Check Docker volume mount: `docker inspect test-mail-server | grep -A5 Mounts`
2. Check inside container: `docker exec test-mail-server ls -la /var/mail/`
3. Check Postfix logs: `docker logs test-mail-server | tail -50`

### SMTPBench Times Out

**Problem**: Messages take too long to send

**Solution**: Adjust timeout:

```bash
smtpbench \
  ... \
  transaction_timeout=60 \
  ...
```

## Advanced Usage

### Test with Authentication

The local test server doesn't require authentication, but you can test auth flows:

```bash
smtpbench \
  recipient=test@local.ingest.lets.qa \
  lb_host=localhost \
  port=25 \
  from_address=loadtest@local.ingest.lets.qa \
  threads=5 \
  messages=50 \
  use_tls=false \
  username=testuser \
  password=testpass
```

### Journal All Messages

Send copies to a journal address:

```bash
smtpbench \
  recipient=test@local.ingest.lets.qa \
  lb_host=localhost \
  port=25 \
  from_address=loadtest@local.ingest.lets.qa \
  threads=5 \
  messages=50 \
  use_tls=false \
  journal_enabled=true \
  journal_address=archive@local.ingest.lets.qa
```

### MX Failover Test

To test MX failover, you'd need multiple mail servers. See the main README for examples.

## Tips for Effective Testing

1. **Start Small**: Begin with 10-100 messages to verify setup
2. **Monitor Resources**: Watch CPU/memory during large tests
3. **Check Logs**: Review success/failure logs after each run
4. **Clean Between Tests**: Remove old logs and mail files for fresh results
5. **Use Unique Run UUIDs**: Each run gets a unique ID for tracking
6. **Test Incrementally**: Gradually increase load to find limits

## Understanding the Output

During a test run, you'll see:

```
  75%|███████▌  | 750/1000 [00:05<00:01, 148.2msg/s, Fail=0, Rate=100.0%, Success=750]
```

- **75%**: Progress percentage
- **750/1000**: Messages sent / total messages
- **148.2msg/s**: Current throughput (messages per second)
- **Fail=0**: Number of failures
- **Rate=100.0%**: Success rate
- **Success=750**: Total successful sends

At the end, you'll see a summary:

```
=== SMTP Load Test Summary ===
Run UUID: abc123...
Total Sent: 1000
Total Failed: 0
Total Retried: 0
Elapsed Time: 6.75 seconds
```

## Next Steps

- Read the full [README.md](README.md) for all features
- Review [SECURITY.md](SECURITY.md) for security best practices
- Contribute at [GitHub](https://github.com/SMTPBench/SMTPBench)

## Support

Having issues? 
- Check the [main README](README.md) troubleshooting section
- Review Docker logs: `docker logs test-mail-server`
- Open an issue on [GitHub](https://github.com/SMTPBench/SMTPBench/issues)

---

**Happy Testing! 📧🚀**

Last updated: 2025-11-18
