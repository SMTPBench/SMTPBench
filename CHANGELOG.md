# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.2.1] - 2026-08-17

### Fixed
- **`port=` is no longer required in offline mode.** A run with `eml_out_dir=` never opens a connection, so demanding a port asked for a value that could not be used. `port=` is still accepted offline (and reported in the summary); when omitted, the summary records `"port": null`. The missing-parameter help no longer lists `port` for offline runs.

### Removed
- **`.pypirc.example`**, which only restated the `~/.pypirc` template that `DEPLOYMENT.md` already inlines. The two details the doc was missing (the `[distutils] index-servers` block and TestPyPI's `repository` URL) moved into `DEPLOYMENT.md`. Packaging and runtime behavior are unaffected.

### Added
- **Python 3.13 and 3.14 are now declared supported.** `requires-python = ">=3.9"` already permitted them and the suite passes on both; only the PyPI classifiers were stale. CI's unit-test job now runs as a matrix across 3.9–3.14 so the classifiers are backed by evidence rather than assertion. The integration job stays on 3.11 (it is gated by Docker, not by interpreter version).

### Changed
- Ruff's `target-version` moved from `py38` to `py39`, matching the `requires-python` floor the project actually declares.

### Documentation
- `--help`, the README required-parameter table, and the Offline EML Output section all record that `port=` is not needed with `eml_out_dir=`. The README's offline example no longer passes an unused `port=`.
- The README's Requirements section names the interpreter versions CI actually exercises.
- `SECURITY.md` now lists `1.2.x` as a supported version.
- `DEPLOYMENT.md`'s version-bump checklist names every file that carries the version, not just three.

## [1.2.0] - 2026-08-04

### Added
- **SMTP AUTH**: `username=`/`password=` with resolution order CLI > environment (`SMTPBENCH_USER`/`SMTPBENCH_PASS`) > `.env` (via `python-dotenv`, path overridable with `dotenv_path=`). Credentials are never written to logs, the summary, or terminal output beyond a one-line warning when passed on the CLI.
- **TLS transport modes**: `tls_mode=starttls|ssl|none` (default `starttls`; `ssl` auto-selected on port 465). This fixes implicit-TLS submission on port 465, which previously never used `SMTP_SSL`. `use_tls=` is retained as a soft-deprecated alias.
- **Whole-run rate cap**: `rate=` (messages/sec) enforced by a shared token bucket across all threads. Mutually exclusive with `delay=`/`random_delay=`.
- **Attachment realism**: `attachment_size=` accepts a range (`10KB-2MB`); new `attachment_dir=` samples a corpus directory with `attachment_probability=` and `attachment_count=A-B`. Per-message selection is seeded from the run UUID for reproducibility. The three attachment modes are mutually exclusive.
- **Summary artifact**: `summary_{timestamp}_{uuid}.json` in the log directory with config, totals, latency percentiles (p50/p95/p99/max, via stdlib `statistics`), and per-MX sent/failed counts.
- **Body-text prefix**: `body_text_dir=PATH` prepends a randomly chosen text file from the directory above the standard message body. Subject line, tracking headers, and footer are preserved. Selection is deterministic per run. Only the chosen filename and character length are logged — never the excerpt text.
- **Offline EML output**: `eml_out_dir=PATH` writes each message to the directory as `{sha256}.eml` instead of sending over SMTP. Fully offline — no DNS/MX lookup and no banner check; the recipient is used only as a header. Composes with attachments and `body_text_dir`. Identical message bytes deduplicate to a single file.
- **Coverage gate**: CI enforces a combined (unit + integration) code-coverage floor via `pytest-cov` + `coverage combine`, with per-suite numbers reported for visibility.
- **Address lists from a file**: `recipient_file=` / `from_file=` / `journal_file=` each read a one-address-per-line file (blank lines and `#` comments ignored, every address validated) and select per message, independently. `*_file_order=random|roundrobin` (default `random`) is set per field. A `*_file` overrides and cannot be combined with its single-value counterpart. `recipient_file` requires `lb_host=` or `eml_out_dir=` (offline); `journal_file` requires `journal=true`. Chosen `from`/`journal` addresses are logged per message; the summary records file/count/order metadata only.

### Changed
- **Development status**: promoted from Beta to Production/Stable.
- **Minimum Python raised to 3.9** to match the `setuptools>=77.0.0` build requirement.
- **Credentials fail fast**: passing only one of `username=`/`password=` (or `SMTPBENCH_USER`/`SMTPBENCH_PASS`) now aborts with a clear error instead of failing opaquely inside `smtplib.login` on every send.
- **`attachment_filename` + `attachment_dir` rejected**: the combination was silently ignored (corpus files keep their own names); it now raises a configuration error.
- **Summary totals derive from per-MX final outcomes**: `totals.sent`/`totals.failed` and `success_rate` now reflect per-message final outcomes (consistent with `per_mx`) instead of counting each retried attempt as a separate failure. `totals.retried` still reports the attempt-level retry count.
- **Journal destination fails fast**: `journal=true` with `recipient_file=` (no single `recipient=` to fall back to) and no `journal_address=`/`journal_file=` now aborts at startup instead of silently journaling nowhere. A present-but-empty `*_file=` value is likewise rejected as a configuration error rather than treated as absent.

### Security
- **Credentials no longer leak under `debug=true`**: `smtplib`'s wire debug is disabled for the duration of `server.login()`, so the (base64, reversible) SASL AUTH exchange is never written to the terminal. The design doc's prior claim that base64 SASL is "obscured" was incorrect and has been corrected.

### Dependencies
- Added `python-dotenv>=1.0.0`.
- Pinned the dev dependency `ruff` to `==0.16.1` so local, CI, and deploy formatting never diverge (newer Ruff versions reformat Python inside Markdown, which broke the `deploy.sh` format gate).

## [1.1.1] - 2026-08-03

### Added
- **Ruff Linting & Formatting**: Adopted Ruff as the linter and formatter (`E, F, I, W, UP` rule set, `E501` left to the formatter), configured in `pyproject.toml`.
- **Lint Gates**: `deploy.sh` and the CI workflow now fail closed on lint or formatting errors; `deploy.sh` resolves Ruff from the deployment environment before publishing.

### Changed
- **Recipient Validation**: Reject recipient addresses containing multiple `@` characters.
- **Integration Test Scoping**: Correlate all integration assertions with the current run UUID so stale messages in the shared mbox can no longer satisfy them; assert Docker command success. `validate_mbox.py` fails closed when no run UUID is available, with an explicit `ALLOW_UNSCOPED_VALIDATION=true` opt-in.

### Security
- **CI Hardening**: Set `persist-credentials: false` on all workflow checkout steps.

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
