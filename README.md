# SMTPBench

[![PyPI version](https://badge.fury.io/py/smtpbench.svg)](https://badge.fury.io/py/smtpbench)
[![PyPI - Downloads](https://img.shields.io/pypi/dm/smtpbench)](https://pypi.org/project/smtpbench/)
[![Python Versions](https://img.shields.io/pypi/pyversions/smtpbench.svg)](https://pypi.org/project/smtpbench/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Tests](https://github.com/SMTPBench/SMTPBench/actions/workflows/pytest.yml/badge.svg)](https://github.com/SMTPBench/SMTPBench/actions/workflows/pytest.yml)

A robust SMTP load testing and benchmarking tool with MX failover support and detailed logging capabilities.

**📦 [Available on PyPI](https://pypi.org/project/smtpbench/)** • **🚀 [Quick Start Guide](LOCAL_TESTING.md)** • **📖 [Documentation](https://github.com/SMTPBench/SMTPBench)**

## ⚠️ Important Notice

**This tool will attempt to send real emails when run against any hostname.** Please be aware:

- **Permission Required**: Ensure you have permission on **both the sending and receiving networks** to use this tool. Unauthorized use may violate terms of service or laws.
- **Email Tracking**: All emails sent by this tool include message counts, thread IDs, and unique run identifiers (UUIDs) in the subject line and body. This enables tracking and identification if issues arise.
- **ISP Blocking**: If running against public hostnames, your ISP may already be blocking outbound SMTP traffic (ports 25, 587, 465). You can try alternate ports, but if these ports are open, you could still be blocked or flagged.
- **Not for Residential Use**: This tool is **not meant to be run from residential internet connections** or personal systems without proper authorization.
- **Not for Malicious Use**: This is **NOT** a tool for denial of service attacks or any malicious activity.
- **Intended Purpose**: This is purely an email benchmarking and load testing tool designed for authorized testing of SMTP infrastructure in controlled environments.

**Use responsibly and ethically.**

## Features

- 🚀 **Multi-threaded Load Testing** - Simulate concurrent SMTP connections
- 🔄 **MX Failover** - Automatic MX record lookup with failover to backup servers
- 📊 **Real-time Progress** - Live progress bar with success rate metrics
- 📝 **Detailed Logging** - Structured JSON logs for success, failures, retries, and debug info
- 🔒 **TLS/STARTTLS Support** - Secure connection support
- ⚙️ **Highly Configurable** - Extensive options for timeouts, retries, and delays
- 🎨 **Color-coded Output** - Easy-to-read terminal output with status colors
- 📬 **Journal Mode** - Optional message journaling mode
- 🐛 **Debug Mode** - Detailed debugging for troubleshooting
- 🐳 **Docker Support** - Run in containers

## Installation

### From PyPI (Recommended)

```bash
pip install smtpbench
```

### Upgrade to Latest Version

```bash
pip install --upgrade smtpbench
```

Or specify a version:

```bash
pip install smtpbench==1.1.0
```

### From Source

```bash
git clone https://github.com/SMTPBench/SMTPBench.git
cd SMTPBench
pip install -e .
```

### Using Docker

```bash
# Build the image
docker build -t smtpbench .

# Run with log volume mount
docker run --rm -v $(pwd)/logs:/app/logs smtpbench \
    recipient=test@local.lets.qa \
    port=587 \
    threads=5 \
    messages=10

# Or run without volume mount (logs stay in container)
docker run --rm smtpbench \
    recipient=test@local.lets.qa \
    port=587 \
    threads=5 \
    messages=10
```

## Quick Start

### Getting Help

```bash
# Show version
smtpbench --version
smtpbench -v

# Show full help with all options
smtpbench --help

# Also works with
smtpbench -h
smtpbench help
smtpbench ?
```

### Basic Usage

```bash
smtpbench recipient=test@local.lets.qa port=587 threads=5 messages=10
```

### With TLS and Custom Settings

```bash
smtpbench \
    recipient=test@local.lets.qa \
    port=587 \
    from_address=loadtest@local.lets.qa \
    threads=10 \
    messages=100 \
    use_tls=true \
    retry_delay=5 \
    max_retries=3 \
    transaction_timeout=30
```

### Using Load Balancer Instead of MX Lookup

```bash
smtpbench \
    recipient=test@local.lets.qa \
    lb_host=smtp.local.lets.qa \
    port=587 \
    threads=5 \
    messages=20
```

### With Attachments

Attach a static file to every generated message:

```bash
smtpbench \
    recipient=test@local.lets.qa \
    port=587 \
    threads=2 \
    messages=5 \
    attachment_path=./sample.pdf
```

Generate synthetic attachments for size-based benchmarking:

```bash
smtpbench \
    recipient=test@local.lets.qa \
    port=587 \
    threads=2 \
    messages=5 \
    attachment_size=1MB \
    attachment_count=2 \
    attachment_filename=payload.bin \
    attachment_mime_type=application/octet-stream
```

> **Attachment safety:** Attachments multiply outbound traffic and downstream storage pressure. SMTPBench prints the per-message attachment size and estimated total attachment payload before sending when attachments are enabled.

### As a Python Module

```bash
python -m smtpbench recipient=test@local.lets.qa port=587 threads=5 messages=10
```

## Configuration Options

For a complete, formatted list of all options with examples, run:
```bash
smtpbench --help
```

### Required Parameters

| Parameter | Description | Example |
|-----------|-------------|---------|
| `recipient` | Target email address | `test@local.lets.qa` |
| `port` | SMTP port number | `587` or `25` |
| `threads` | Number of concurrent threads | `10` |
| `messages` | Messages per thread (0 for infinite) | `100` |

> **Note:** If any required parameter is missing, SMTPBench will display a helpful error message with examples.

### Optional Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `lb_host` | *(auto MX lookup)* | Load balancer/SMTP host (skips MX lookup) |
| `from_address` | `no-reply@localhost` | Sender email address |
| `retry_delay` | `20` | Seconds to wait between retries |
| `use_tls` | `true` | Enable TLS/STARTTLS |
| `delay` | `0` | Fixed delay between messages (seconds) |
| `random_delay` | `false` | Random 1-15 second delay between messages |
| `transaction_timeout` | `20` | SMTP transaction timeout (seconds) |
| `max_retries` | `3` | Maximum retry attempts per message |
| `client_hostname` | *(system hostname)* | Client hostname for SMTP HELO/EHLO |
| `logfile_output` | `./logs` | Directory for log files |
| `journal` | `false` | Enable journal mode |
| `journal_address` | *(same as recipient)* | Email address for journal copies |
| `debug` | `false` | Enable debug logging |
| `attachment_path` | *(none)* | Attach a specific file to every message |
| `attachment_size` | *(none)* | Generate synthetic attachment(s); accepts a fixed size or range (`512KB`, `10KB-2MB`) |
| `attachment_dir` | *(none)* | Sample attachments from a corpus directory (mutually exclusive with `attachment_path`/`attachment_size`) |
| `attachment_probability` | `1.0` | Probability (0.0–1.0) that any given message gets an attachment (used with `attachment_size`/`attachment_dir`) |
| `attachment_count` | `1` | Number of attachments per message; accepts a range (`1-3`) |
| `attachment_filename` | source/generated name | Override attachment filename (`payload.bin` becomes `payload-1.bin`, `payload-2.bin`, etc. when count > 1) |
| `attachment_mime_type` | auto-detected / `application/octet-stream` | Override attachment MIME type |
| `tls_mode` | `starttls` (or `ssl` on port 465) | TLS transport: `starttls`, `ssl`, or `none`. Use `ssl` for port 465 implicit-TLS. `use_tls=` is a deprecated alias. |
| `rate` | *(none)* | Whole-run cap in messages/sec, enforced by a shared token bucket. Mutually exclusive with `delay=`/`random_delay=`. |
| `username` | *(none)* | SMTP AUTH username. Prefer `SMTPBENCH_USER` env var or `.env` over CLI (CLI credentials are visible in `ps`/shell history). |
| `password` | *(none)* | SMTP AUTH password. Prefer `SMTPBENCH_PASS` env var or `.env` over CLI. |
| `dotenv_path` | `.env` | Path to a `.env` file for credential resolution (default: `.env` in current directory). |

### SMTP Authentication

SMTPBench resolves credentials in this order: **CLI arguments → environment variables → `.env` file**.

Preferred — set environment variables or use a `.env` file so credentials are not visible in process listings:

```bash
# Via environment variables
export SMTPBENCH_USER=myuser
export SMTPBENCH_PASS=mypassword
smtpbench recipient=test@example.com port=587 threads=5 messages=10

# Or via a .env file (default path: .env in current directory)
echo "SMTPBENCH_USER=myuser" >> .env
echo "SMTPBENCH_PASS=mypassword" >> .env
smtpbench recipient=test@example.com port=587 threads=5 messages=10

# Custom .env path
smtpbench recipient=test@example.com port=587 threads=5 messages=10 dotenv_path=/etc/smtpbench.env
```

Discouraged — passing credentials on the CLI makes them visible in `ps`, `top`, and shell history:

```bash
# ⚠ Credentials visible in ps/shell history — prefer env/.env instead
smtpbench recipient=test@example.com port=587 threads=5 messages=10 \
    username=myuser password=mypassword
```

SMTPBench prints a warning when credentials are supplied this way.

### TLS Modes

Use `tls_mode=` to control the TLS transport. The default is `starttls` (upgrade an initially plain connection); port 465 defaults to `ssl` (implicit TLS from the start):

```bash
# STARTTLS on port 587 (default)
smtpbench recipient=test@example.com port=587 threads=5 messages=10 tls_mode=starttls

# Implicit SSL on port 465
smtpbench recipient=test@example.com port=465 threads=5 messages=10 tls_mode=ssl

# Plain (no TLS)
smtpbench recipient=test@example.com port=25 threads=5 messages=10 tls_mode=none
```

The `use_tls=true/false` flag is a deprecated alias for `tls_mode=starttls/none`.

### Rate Limiting

Cap the whole-run throughput with `rate=` (messages/sec). The limit is enforced by a shared token bucket across all threads and is mutually exclusive with `delay=`/`random_delay=`:

```bash
# Cap at 10 messages/sec across all threads
smtpbench recipient=test@example.com port=587 threads=10 messages=100 rate=10
```

### Corpus-directory Attachments

Sample attachments randomly from a directory of real files:

```bash
smtpbench \
    recipient=test@example.com \
    port=587 \
    threads=5 \
    messages=20 \
    attachment_dir=./corpus \
    attachment_probability=0.8 \
    attachment_count=1-3
```

- `attachment_dir=` — directory to sample from (mutually exclusive with `attachment_path`/`attachment_size`)
- `attachment_probability=` — probability (0.0–1.0) that a given message gets attachments (default: `1.0`)
- `attachment_count=` — number of files to attach; accepts a range like `1-3` (default: `1`)
- `attachment_size=` also accepts a range, e.g. `10KB-2MB`, to generate variable-sized synthetic attachments

Per-message selection is seeded from the run UUID so results are reproducible.

## Output and Logging

SMTPBench creates structured JSON logs in the specified log directory:

### Log Files

- **`success_TIMESTAMP_UUID.log`** - Successfully sent messages
- **`fail_TIMESTAMP_UUID.log`** - Failed message attempts
- **`retry_TIMESTAMP_UUID.log`** - Retry attempts
- **`debug_TIMESTAMP_UUID.log`** - Debug information (when debug=true)

### Log Entry Format

```json
{
  "timestamp": "2025-11-17T21:15:00",
  "run_uuid": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "client_hostname": "loadtest-server",
  "status": "success",
  "thread_id": 1,
  "message_id": 42,
  "duration_seconds": 0.523,
  "attempt": 1,
  "retry_number": null,
  "mx_host_used": "mx1.local.lets.qa",
  "recipients": ["test@local.lets.qa"],
  "attachments": [
    {
      "filename": "payload.bin",
      "size_bytes": 1048576,
      "mime_type": "application/octet-stream",
      "source": "generated"
    }
  ],
  "error": null
}
```

### Summary Artifact

After every run, SMTPBench writes a `summary_{timestamp}_{uuid}.json` file to the log directory. It contains the run configuration, send totals, per-MX sent/failed counts, and latency percentiles:

```json
{
  "run_uuid": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "client_hostname": "loadtest-server",
  "started_at": "2026-08-04_10-30-00",
  "elapsed_seconds": 42.5,
  "config": {
    "threads": 5,
    "messages": 100,
    "rate": null,
    "tls_mode": "starttls",
    "auth": false,
    "port": 587
  },
  "totals": {
    "sent": 495,
    "failed": 5,
    "retried": 2,
    "success_rate": 99.0
  },
  "latency_ms": {
    "p50": 120,
    "p95": 350,
    "p99": 510,
    "max": 820
  },
  "per_mx": {
    "mx1.example.com": {"sent": 495, "failed": 5}
  }
}
```

Use the summary file to gate CI pipelines on latency budgets:

```bash
# Fail the build if p95 latency exceeds 2s
python -c "import json,sys; d=json.load(open(sys.argv[1])); sys.exit(1 if (d['latency_ms'] or {}).get('p95',0) > 2000 else 0)" logs/summary_*.json
```

### Email Message Format

Each email sent by SMTPBench includes tracking headers and identifiers for correlation:

```
From: loadtest@local.lets.qa
To: test@local.lets.qa
Subject: Quick test from thread 3 message 7 [a1b2c3d4-e5f6-7890-abcd-ef1234567890]
X-SMTPBench-Run-UUID: a1b2c3d4-e5f6-7890-abcd-ef1234567890
X-SMTPBench-Thread-ID: 3
X-SMTPBench-Message-ID: 7
Content-Type: multipart/mixed; boundary="===============1234567890=="
MIME-Version: 1.0

--===============1234567890==
Content-Type: text/plain; charset="us-ascii"
MIME-Version: 1.0
Content-Transfer-Encoding: 7bit

Quick test from thread 3 message 7 [a1b2c3d4-e5f6-7890-abcd-ef1234567890]

--
SMTPBench Load Testing Tool
https://github.com/SMTPBench/SMTPBench
--===============1234567890==--
```

**Key Fields That Change Per Message:**
- `Subject` - Contains thread ID, message ID, and run UUID
- `X-SMTPBench-Thread-ID` - Identifies which thread sent the message (1 to N threads)
- `X-SMTPBench-Message-ID` - Message number within that thread (1 to N messages)

**Key Fields That Stay Constant Per Run:**
- `X-SMTPBench-Run-UUID` - Unique identifier for the entire test run
- `From` - Sender address (unless changed)
- `To` - Recipient address (unless changed)

**Example: Messages from the Same Run**

Thread 1, Message 1:
```
Subject: Quick test from thread 1 message 1 [a1b2c3d4-e5f6-7890-abcd-ef1234567890]
X-SMTPBench-Run-UUID: a1b2c3d4-e5f6-7890-abcd-ef1234567890
X-SMTPBench-Thread-ID: 1
X-SMTPBench-Message-ID: 1
```

Thread 1, Message 2:
```
Subject: Quick test from thread 1 message 2 [a1b2c3d4-e5f6-7890-abcd-ef1234567890]
X-SMTPBench-Run-UUID: a1b2c3d4-e5f6-7890-abcd-ef1234567890  ← Same run UUID
X-SMTPBench-Thread-ID: 1                                      ← Same thread
X-SMTPBench-Message-ID: 2                                     ← Different message
```

Thread 3, Message 7:
```
Subject: Quick test from thread 3 message 7 [a1b2c3d4-e5f6-7890-abcd-ef1234567890]
X-SMTPBench-Run-UUID: a1b2c3d4-e5f6-7890-abcd-ef1234567890  ← Same run UUID
X-SMTPBench-Thread-ID: 3                                      ← Different thread
X-SMTPBench-Message-ID: 7                                     ← Different message
```

**Example: Messages from Different Runs**

First run:
```
Subject: Quick test from thread 1 message 1 [a1b2c3d4-e5f6-7890-abcd-ef1234567890]
X-SMTPBench-Run-UUID: a1b2c3d4-e5f6-7890-abcd-ef1234567890
```

Second run (different UUID):
```
Subject: Quick test from thread 1 message 1 [f9e8d7c6-b5a4-3210-fedc-ba9876543210]
X-SMTPBench-Run-UUID: f9e8d7c6-b5a4-3210-fedc-ba9876543210  ← Different run
```

**Use Cases for Headers:**
- **Tracking**: Follow individual messages across distributed mail systems
- **Correlation**: Match emails with JSON log entries via run UUID
- **Testing**: Validate message delivery and filter test data
- **Debugging**: Identify which test run generated specific emails
- **Analysis**: Aggregate metrics by run UUID or thread ID

### Terminal Output

SMTPBench displays real-time progress with color-coded success rates:

```
[INFO] Run UUID: a1b2c3d4-e5f6-7890-abcd-ef1234567890
[INFO] Client Hostname: loadtest-server
[INFO] MX lookup for local.lets.qa:
  - mx1.local.lets.qa (priority 10)
  - mx2.local.lets.qa (priority 20)
[INFO] SMTP banner check passed for mx1.local.lets.qa:587

100%|████████████████| 500/500 [02:15<00:00, 3.70msg/s, Success=487, Fail=13, Rate=97.4%]

=== SMTP Load Test Summary ===
Run UUID: a1b2c3d4-e5f6-7890-abcd-ef1234567890
Client Hostname: loadtest-server
SMTP Hosts Tried: mx1.local.lets.qa, mx2.local.lets.qa
Total Sent: 487
Total Failed: 13
Total Retried: 8
Elapsed Time: 135.42 seconds
Logs saved in: /path/to/logs
```

## Use Cases (adjust samples for your needs)

### Load Testing
Test SMTP server capacity and performance under concurrent load:
```bash
smtpbench recipient=test@local.lets.qa port=587 threads=50 messages=1000
```

### Failover Testing
Verify MX failover behavior by testing multiple mail servers:
```bash
smtpbench recipient=test@local.lets.qa port=25 threads=10 messages=100
```

### Connection Testing
Quick connectivity test with minimal load:
```bash
smtpbench recipient=test@local.lets.qa port=587 threads=1 messages=1
```

### Sustained Load Testing
Run continuous load with random delays:
```bash
smtpbench \
    recipient=test@local.lets.qa \
    port=587 \
    threads=5 \
    messages=0 \
    random_delay=true
```

## Examples

### Test with Journal Mode
```bash
smtpbench \
    recipient=test@local.lets.qa \
    port=587 \
    threads=5 \
    messages=10 \
    journal=true \
    journal_address=archive@local.lets.qa
```

### Debug Mode for Troubleshooting
```bash
smtpbench \
    recipient=test@local.lets.qa \
    port=587 \
    threads=1 \
    messages=1 \
    debug=true
```

### High-Volume Load Test
```bash
smtpbench \
    recipient=test@local.lets.qa \
    port=587 \
    from_address=loadtest@local.lets.qa \
    threads=100 \
    messages=1000 \
    use_tls=true \
    retry_delay=10 \
    max_retries=5 \
    transaction_timeout=30 \
    logfile_output=/var/log/smtpbench
```

## Requirements

- Python 3.8 or higher
- Dependencies (automatically installed):
  - `dnspython>=2.0.0`
  - `tqdm>=4.0.0`
  - `colorama>=0.4.0`

## Development

### Setup Development Environment

```bash
git clone https://github.com/SMTPBench/SMTPBench.git
cd SMTPBench
pip install -e ".[dev]"
```

This installs the runtime dependencies plus the dev tools (`pytest` and `ruff`).

### Linting and Formatting

SMTPBench uses [Ruff](https://docs.astral.sh/ruff/) for both linting and formatting:

```bash
# Lint
ruff check .

# Lint and auto-fix
ruff check . --fix

# Format code
ruff format .

# Check formatting without changing files (as CI does)
ruff format --check .
```

### Running Tests

SMTPBench includes both unit tests and integration tests.

#### Unit Tests

Run the unit test suite:
```bash
pytest -v -m "not integration"
```

#### Integration Tests

Integration tests use Docker Compose to spin up a real SMTP server and validate end-to-end functionality:

```bash
# Run integration tests (requires Docker)
pytest -v -m "integration"

# Or use the shell script
./tests/run_integration_test.sh
```

The integration tests:
- Start a local test mail server using [local-test-mail-server](https://github.com/lets-qa/local-test-mail-server)
- Run SMTPBench to send emails
- Validate emails are received in the mbox file
- Verify log files are created correctly
- Check message format and content

#### Run All Tests

```bash
pytest -v
```

### CI/CD

Checks run automatically on pull requests via GitHub Actions:
- **Lint** - Ruff lint and format checks
- **Unit tests** - Fast tests without external dependencies
- **Integration tests** - Full end-to-end tests with Docker Compose

See `.github/workflows/pytest.yml` for details.

## Troubleshooting

### Getting Help

If you're unsure about available options or syntax:
```bash
smtpbench --help  # Display full help with all options and examples
```

### Invalid Arguments

If you see an error like `Invalid argument format`, ensure you're using the `key=value` format:
```bash
# ✗ Wrong
smtpbench --recipient test@example.com

# ✓ Correct
smtpbench recipient=test@example.com port=587 threads=5 messages=10
```

### Missing Required Parameters

If parameters are missing, SMTPBench will show which ones are required:
```bash
$ smtpbench recipient=test@example.com
✗ Missing required parameter(s): port, threads, messages
```

### Connection Timeouts

If you're experiencing connection timeouts, try increasing the `transaction_timeout`:
```bash
smtpbench recipient=test@local.lets.qa port=587 threads=5 messages=10 transaction_timeout=60
```

### MX Lookup Failures

If MX lookup is failing, use `lb_host` to specify the SMTP server directly:
```bash
smtpbench recipient=test@local.lets.qa lb_host=smtp.local.lets.qa port=587 threads=5 messages=10
```

### Debug Mode

Enable debug mode for detailed SMTP protocol information:
```bash
smtpbench recipient=test@local.lets.qa port=587 threads=1 messages=1 debug=true
```

Check the debug log file in your logs directory for detailed information.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Author

**Randall Morse** - [rmorse@lets.qa](mailto:rmorse@lets.qa)

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for version history.

## Support

For issues, questions, or contributions, please visit the [GitHub repository](https://github.com/SMTPBench/SMTPBench).
