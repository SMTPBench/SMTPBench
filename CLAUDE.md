# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

SMTPBench is a multi-threaded SMTP load-testing CLI published to PyPI as `smtpbench`. It sends **real emails** to whatever host it resolves — see the warning in README.md before running it against anything.

## Commands

```bash
# Install for development (editable) + dev tools (pytest, ruff)
pip install -e ".[dev]"

# Lint and format (ruff owns both)
ruff check .            # lint
ruff check . --fix      # lint + autofix
ruff format .           # format
ruff format --check .   # verify formatting (what CI runs)

# Unit tests (fast, no external services)
pytest -v -m "not integration"

# A single test / class / method
pytest tests/test_smtpbench.py::TestMXLookup::test_mx_lookup_success -v

# Integration tests (require Docker — spins up a real Postfix mail server)
pytest -v -m "integration"
./tests/run_integration_test.sh   # equivalent shell wrapper

# Run the tool locally
smtpbench recipient=test@local.lets.qa port=587 threads=5 messages=10
python -m smtpbench recipient=... port=... threads=... messages=...

# Publish to PyPI (interactive; runs unit tests first, refuses on version mismatch)
./deploy.sh
```

Ruff is the linter and formatter (configured in `pyproject.toml` under `[tool.ruff]`). The lint rule set is `E, F, I, W, UP` with `E501` ignored — line length is left to the formatter so the two don't fight. `BLE001` (blind-except) and the `global`-variable rules are intentionally *not* enabled: the broad `except Exception` in the send path and the module-global threading model are by design here.

## Architecture

Essentially the entire application lives in `smtpbench/cli.py` (~600 lines). `__init__.py` exposes `main` and the version; `__main__.py` enables `python -m smtpbench`. Understanding the file means understanding these things that span it:

- **Module-level global state.** Counters (`success_count`, `fail_count`, `retry_count`), the stop flag (`stop_requested`), run metadata (`run_uuid`, `run_timestamp`, `client_hostname`), the resolved `mx_hosts` list, and logging config (`log_dir`, `journal_*`, `debug_*`) are all module globals mutated across threads under a single `threading.Lock` (`lock`). Worker threads read/write these directly rather than passing state around. **Consequence:** tests must reset globals — `tests/conftest.py` has an autouse `reset_globals` fixture that does this before and after every test. New global state that affects test outcomes should be added there too.

- **Argument parsing is `key=value`, not argparse.** `parse_args()` splits `sys.argv` on the first `=` per token. `-v/--version/version` and `-h/--help/help/?` (and zero args) short-circuit with `sys.exit(0)` before parsing. Required keys (`recipient`, `port`, `threads`, `messages`) are validated in `main()`, not the parser. Booleans are strings compared to `"true"`.

- **Send path with MX failover.** `main()` → spawns `threads` worker threads → each `worker()` loops `messages` times (0 = infinite) → `send_email()` handles retry/backoff → `try_send_to_mx_hosts()` walks `mx_hosts` in priority order, returning on the first success. `mx_hosts` is populated either from `lb_host` (single host, skips DNS) or `mx_lookup_all()` (DNS MX records sorted by preference). A pre-flight `check_smtp_banner()` on the first host aborts early if the server is unreachable.

- **Structured JSON logging.** `setup_logging()` creates four file loggers (`success`, `fail`, `retry`, `debug`) named `{name}_{timestamp}_{uuid}.log` in `log_dir`. `log_json()` writes one JSON object per line. Debug logging is gated on `debug_enabled` and also flips `smtplib` debug level.

- **Attachments carry raw bytes internally but never in logs.** `build_attachment_configs()` returns dicts that include a `content` key (the actual bytes, from a file or synthetic `b"0" * size`). That `content` is stripped before anything is logged — both `attachment_metadata()` and `log_json()` filter out the `content` key. When touching attachment handling, preserve this separation: bytes flow to `create_message()`, only metadata flows to logs.

## Conventions that matter

- **Version lives in two files and must match.** `pyproject.toml` `version` and `smtpbench/__init__.py` `__version__`. `deploy.sh` aborts on mismatch; keep them in lockstep and update `CHANGELOG.md`.
- **Integration tests depend on external infrastructure.** They shell out to `docker compose -f docker-compose.test.yml`, pull `ghcr.io/lets-qa/local-test-mail-server`, send mail, and validate the resulting mbox at `test-mail/root`. They filter validated messages by the run UUID to avoid false positives from prior runs. The `dockerfile` (lowercase) is what the compose file builds.
- **CI** (`.github/workflows/pytest.yml`) runs unit and integration jobs separately on every PR to `main`.
