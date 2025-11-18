# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0] - 2025-11-18

### Added
- **Comprehensive Help System**: Added `--help`, `-h`, `help`, and `?` flags with beautifully formatted, color-coded help output
- **Version Information**: Added `--version`, `-v`, and `version` flags to display version and GitHub URL
- **Enhanced Email Tracking**: Added custom headers to all emails:
  - `X-SMTPBench-Run-UUID`: Unique run identifier for correlation
  - `X-SMTPBench-Thread-ID`: Thread number that sent the message
  - `X-SMTPBench-Message-ID`: Message number within the thread
- **Integration Test Suite**: Complete Docker Compose-based integration tests
  - Automated testing against real SMTP server ([local-test-mail-server](https://github.com/lets-qa/local-test-mail-server))
  - mbox validation with UUID filtering to prevent false positives
  - Pytest integration with `@pytest.mark.integration` marker
  - GitHub Actions CI/CD integration
- **Test Validation Scripts**: Python scripts to validate email delivery in mbox format
- **Shell Test Runner**: Convenient `run_integration_test.sh` for easy testing

### Changed
- **Email Footer**: Updated from "SMTP Load Test Tool" to "SMTPBench Load Testing Tool" with GitHub link
- **Error Messages**: Significantly improved error messages with:
  - Color-coded output (red for errors, yellow for hints, cyan for examples)
  - Helpful examples for common mistakes
  - Links to full help documentation
  - Clear parameter descriptions when missing required arguments
- **Docker Configuration**: Updated Dockerfile to use package-based installation
- **Documentation**: Extensive README updates including:
  - Email message format with header examples
  - Sample emails showing what changes per message vs per run
  - Complete testing documentation
  - Troubleshooting section with help system guidance
  - CI/CD pipeline documentation

### Improved
- **Validation**: Email validation now uses run UUID to filter messages, preventing false positives from previous test runs
- **Testing**: Split unit and integration tests in CI/CD pipeline for better organization
- **Docker Compose**: Optimized mail server configuration for reliable test message delivery

### Fixed
- **Docker Image**: Corrected package structure for proper installation
- **Mail Server Config**: Fixed Postfix configuration to deliver to local mailbox correctly
- **Test Reliability**: Enhanced test validation to check only current run's messages

## [1.0.0] - 2025-11-17

### Added
- Initial release of SMTPBench
- Multi-threaded SMTP load testing
- MX record lookup with automatic failover
- Configurable retry logic with delays
- Detailed JSON logging (success, fail, retry, debug)
- Progress bar with real-time success rate
- TLS/STARTTLS support
- Journal mode for message copying
- Debug mode for detailed troubleshooting
- Docker support
- Configurable timeouts and delays
- Color-coded output for better readability
