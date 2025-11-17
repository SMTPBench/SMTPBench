# SMTPBench

[![PyPI version](https://badge.fury.io/py/smtpbench.svg)](https://badge.fury.io/py/smtpbench)
[![Python Versions](https://img.shields.io/pypi/pyversions/smtpbench.svg)](https://pypi.org/project/smtpbench/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A robust SMTP load testing and benchmarking tool with MX failover support and detailed logging capabilities.

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

### From Source

```bash
git clone https://github.com/SMTPBench/SMTPBench.git
cd SMTPBench
pip install -e .
```

### Using Docker

```bash
docker build -t smtpbench .
docker run --rm -v $(pwd)/logs:/app/logs smtpbench \
    recipient=test@local.lets.qa \
    port=587 \
    threads=5 \
    messages=10
```

## Quick Start

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

### As a Python Module

```bash
python -m smtpbench recipient=test@local.lets.qa port=587 threads=5 messages=10
```

## Configuration Options

### Required Parameters

| Parameter | Description | Example |
|-----------|-------------|---------|
| `recipient` | Target email address | `test@local.lets.qa` |
| `port` | SMTP port number | `587` or `25` |
| `threads` | Number of concurrent threads | `10` |
| `messages` | Messages per thread (0 for infinite) | `100` |

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
  "error": null
}
```

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

## Use Cases

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
pip install -e .
```

### Run Tests

```bash
pytest tests/
```

## Troubleshooting

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
