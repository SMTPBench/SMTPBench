"""Unit tests for SMTPBench"""

import json
import logging
import random
import smtplib
import sys
from contextlib import ExitStack
from unittest.mock import MagicMock, Mock, call, patch

import pytest

from smtpbench import cli
from smtpbench.cli import (
    check_smtp_banner,
    color_rate,
    create_message,
    log_json,
    main,
    mx_lookup_all,
    parse_args,
    send_email,
    try_send_to_mx_hosts,
)


class TestArgumentParsing:
    """Test command-line argument parsing"""

    def test_parse_args_valid(self):
        """Test parsing valid key=value arguments"""
        sys.argv = ["smtpbench", "recipient=test@local.lets.qa", "port=587", "threads=5"]
        args = parse_args()
        assert args["recipient"] == "test@local.lets.qa"
        assert args["port"] == "587"
        assert args["threads"] == "5"

    def test_parse_args_with_spaces(self):
        """Test parsing arguments with spaces around equals"""
        sys.argv = ["smtpbench", "recipient = test@local.lets.qa", "port = 587"]
        args = parse_args()
        assert args["recipient"] == "test@local.lets.qa"
        assert args["port"] == "587"

    def test_parse_args_invalid_format(self):
        """Test that invalid argument format exits"""
        sys.argv = ["smtpbench", "invalid_arg"]
        with pytest.raises(SystemExit):
            parse_args()

    def test_parse_args_help_flag(self):
        """Test that help flags trigger help display"""
        for flag in ["--help", "-h", "help", "?"]:
            sys.argv = ["smtpbench", flag]
            with pytest.raises(SystemExit) as exc_info:
                parse_args()
            assert exc_info.value.code == 0  # Help exits with 0

    def test_parse_args_version_flag(self):
        """Test that version flags trigger version display"""
        for flag in ["--version", "-v", "version"]:
            sys.argv = ["smtpbench", flag]
            with pytest.raises(SystemExit) as exc_info:
                parse_args()
            assert exc_info.value.code == 0  # Version exits with 0

    def test_parse_args_no_arguments(self):
        """Test that no arguments shows help"""
        sys.argv = ["smtpbench"]
        with pytest.raises(SystemExit) as exc_info:
            parse_args()
        assert exc_info.value.code == 0  # Help exits with 0


class TestColorRate:
    """Test color-coded success rate formatting"""

    def test_color_rate_green(self):
        """Test green color for >= 90% success rate"""
        result = color_rate(95.5)
        assert "95.5%" in result
        assert "\033[32m" in result  # Green color code

    def test_color_rate_yellow(self):
        """Test yellow color for 70-89% success rate"""
        result = color_rate(85.0)
        assert "85.0%" in result
        assert "\033[33m" in result  # Yellow color code

    def test_color_rate_red(self):
        """Test red color for < 70% success rate"""
        result = color_rate(50.0)
        assert "50.0%" in result
        assert "\033[31m" in result  # Red color code

    def test_color_rate_boundary_90(self):
        """Test boundary at 90%"""
        result = color_rate(90.0)
        assert "\033[32m" in result  # Should be green

    def test_color_rate_boundary_70(self):
        """Test boundary at 70%"""
        result = color_rate(70.0)
        assert "\033[33m" in result  # Should be yellow


class TestAttachments:
    """Test attachment configuration and MIME construction"""

    def test_create_message_attaches_files_and_preserves_tracking_headers(self, tmp_path):
        """Attachment-enabled messages remain multipart and keep SMTPBench headers."""
        from smtpbench.cli import build_attachment_plan

        attachment = tmp_path / "evidence.txt"
        attachment.write_text("payload", encoding="utf-8")
        plan = build_attachment_plan({"attachment_path": str(attachment)})
        attachment_configs = plan.select_for_message(random.Random("seed"))

        message = create_message(
            recipient="test@local.lets.qa",
            from_address="sender@local.lets.qa",
            thread_id=3,
            message_id=7,
            attachment_configs=attachment_configs,
        )

        assert message["X-SMTPBench-Thread-ID"] == "3"
        assert message["X-SMTPBench-Message-ID"] == "7"
        parts = message.get_payload()
        assert len(parts) == 2
        assert parts[0].get_content_type() == "text/plain"
        assert parts[1].get_filename() == "evidence.txt"
        assert parts[1].get_content_type() == "text/plain"
        assert parts[1].get_payload(decode=True) == b"payload"


class TestAttachmentPlan:
    """Test per-message attachment selection."""

    def test_no_attachment_args_returns_none(self):
        from smtpbench.cli import build_attachment_plan

        assert build_attachment_plan({}) is None

    def test_static_path_selected_every_message(self, tmp_path):
        from smtpbench.cli import build_attachment_plan

        f = tmp_path / "sample.pdf"
        f.write_bytes(b"hello world")
        plan = build_attachment_plan({"attachment_path": str(f)})
        rng = random.Random("seed")
        configs = plan.select_for_message(rng)
        assert len(configs) == 1
        assert configs[0]["filename"] == "sample.pdf"
        assert configs[0]["size_bytes"] == len(b"hello world")
        assert configs[0]["source"] == "file"
        assert configs[0]["content"] == b"hello world"

    def test_conflicting_modes_rejected(self, tmp_path):
        from smtpbench.cli import build_attachment_plan

        with pytest.raises(ValueError):
            build_attachment_plan(
                {"attachment_path": str(tmp_path / "x"), "attachment_size": "1KB"}
            )

    def test_count_with_path_rejected(self, tmp_path):
        from smtpbench.cli import build_attachment_plan

        f = tmp_path / "s.bin"
        f.write_bytes(b"x")
        with pytest.raises(ValueError):
            build_attachment_plan({"attachment_path": str(f), "attachment_count": "2"})

    def test_size_range_bounds_and_count(self):
        from smtpbench.cli import build_attachment_plan

        plan = build_attachment_plan({"attachment_size": "1KB-2KB", "attachment_count": "2-2"})
        rng = random.Random("seed")
        configs = plan.select_for_message(rng)
        assert len(configs) == 2
        for c in configs:
            assert 1024 <= c["size_bytes"] <= 2048
            assert c["source"] == "generated"
            assert len(c["content"]) == c["size_bytes"]

    def test_probability_zero_yields_no_attachments(self):
        from smtpbench.cli import build_attachment_plan

        plan = build_attachment_plan({"attachment_size": "1KB", "attachment_probability": "0"})
        assert plan.select_for_message(random.Random("seed")) == []

    def test_selection_is_deterministic_for_same_seed(self):
        from smtpbench.cli import build_attachment_plan

        plan = build_attachment_plan({"attachment_size": "1KB-9KB", "attachment_count": "1-3"})
        a = plan.select_for_message(random.Random("run:1:1"))
        b = plan.select_for_message(random.Random("run:1:1"))
        assert [c["size_bytes"] for c in a] == [c["size_bytes"] for c in b]

    def test_dir_mode_reads_corpus_and_caps_count(self, tmp_path):
        from smtpbench.cli import build_attachment_plan

        (tmp_path / "a.txt").write_bytes(b"aaa")
        (tmp_path / "b.txt").write_bytes(b"bbbb")
        plan = build_attachment_plan({"attachment_dir": str(tmp_path), "attachment_count": "5-5"})
        configs = plan.select_for_message(random.Random("seed"))
        # count is capped at corpus size (2 files)
        assert len(configs) == 2
        assert {c["filename"] for c in configs} == {"a.txt", "b.txt"}
        assert all(c["source"] == "dir" for c in configs)

    def test_empty_dir_rejected(self, tmp_path):
        from smtpbench.cli import build_attachment_plan

        with pytest.raises(ValueError):
            build_attachment_plan({"attachment_dir": str(tmp_path)})

    def test_dir_mode_rejects_attachment_filename(self, tmp_path):
        from smtpbench.cli import build_attachment_plan

        (tmp_path / "a.txt").write_bytes(b"aaa")
        with pytest.raises(ValueError, match="attachment_filename is not supported"):
            build_attachment_plan(
                {"attachment_dir": str(tmp_path), "attachment_filename": "override.bin"}
            )

    def test_expected_bytes_per_message(self):
        from smtpbench.cli import build_attachment_plan

        plan = build_attachment_plan(
            {
                "attachment_size": "1000-3000",
                "attachment_count": "1-3",
                "attachment_probability": "0.5",
            }
        )
        # 0.5 * mean_count(2) * mean_size(2000) = 2000
        assert plan.expected_bytes_per_message() == pytest.approx(2000.0)


class TestLogJSON:
    """Test JSON logging functionality"""

    def test_log_json_success(self):
        """Test logging successful email"""
        mock_logger = Mock()
        log_json(
            mock_logger,
            status="success",
            thread_id=1,
            message_id=42,
            duration=0.523,
            mx_host_used="mx1.local.lets.qa",
            recipients=["test@local.lets.qa"],
        )

        # Verify logger was called
        assert mock_logger.info.called
        call_args = mock_logger.info.call_args[0][0]
        log_entry = json.loads(call_args)

        # Verify log structure
        assert log_entry["status"] == "success"
        assert log_entry["thread_id"] == 1
        assert log_entry["message_id"] == 42
        assert log_entry["duration_seconds"] == 0.523
        assert log_entry["mx_host_used"] == "mx1.local.lets.qa"
        assert log_entry["recipients"] == ["test@local.lets.qa"]
        assert log_entry["error"] is None

    def test_log_json_includes_attachment_metadata(self):
        """Test attachment metadata is logged without raw content bytes."""
        mock_logger = Mock()
        attachments = [
            {
                "filename": "payload.bin",
                "size_bytes": 2048,
                "mime_type": "application/octet-stream",
                "source": "generated",
            }
        ]

        log_json(
            mock_logger,
            status="success",
            thread_id=1,
            message_id=1,
            duration=0.5,
            attachments=attachments,
        )

        call_args = mock_logger.info.call_args[0][0]
        log_entry = json.loads(call_args)

        assert log_entry["attachments"] == attachments
        assert "content" not in log_entry["attachments"][0]

    def test_log_json_with_error(self):
        """Test logging failed email with error"""
        mock_logger = Mock()
        error = Exception("Connection timeout")

        log_json(
            mock_logger,
            status="fail",
            thread_id=2,
            message_id=10,
            duration=1.5,
            error=error,
            attempt=2,
            retry_number=1,
            mx_host_used="mx2.local.lets.qa",
            recipients=["test@local.lets.qa"],
        )

        call_args = mock_logger.info.call_args[0][0]
        log_entry = json.loads(call_args)

        assert log_entry["status"] == "fail"
        assert log_entry["error"] == "Connection timeout"
        assert log_entry["attempt"] == 2
        assert log_entry["retry_number"] == 1

    def test_log_json_required_fields(self):
        """Test that all required fields are present"""
        mock_logger = Mock()
        log_json(mock_logger, status="success", thread_id=1, message_id=1, duration=1.0)

        call_args = mock_logger.info.call_args[0][0]
        log_entry = json.loads(call_args)

        # Check required fields exist
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
            assert field in log_entry


class TestMXLookup:
    """Test MX record lookup functionality"""

    @patch("smtpbench.cli.dns.resolver.resolve")
    def test_mx_lookup_success(self, mock_resolve):
        """Test successful MX lookup"""
        # Mock DNS response
        mock_mx1 = Mock()
        mock_mx1.preference = 10
        mock_mx1.exchange = Mock()
        mock_mx1.exchange.__str__ = Mock(return_value="mx1.local.lets.qa.")

        mock_mx2 = Mock()
        mock_mx2.preference = 20
        mock_mx2.exchange = Mock()
        mock_mx2.exchange.__str__ = Mock(return_value="mx2.local.lets.qa.")

        mock_resolve.return_value = [mock_mx1, mock_mx2]

        result = mx_lookup_all("test@local.lets.qa")

        assert len(result) == 2
        assert result[0] == "mx1.local.lets.qa"
        assert result[1] == "mx2.local.lets.qa"
        mock_resolve.assert_called_once_with("local.lets.qa", "MX")

    @patch("smtpbench.cli.dns.resolver.resolve")
    def test_mx_lookup_priority_order(self, mock_resolve):
        """Test MX records are sorted by priority"""
        # Mock DNS response with records out of order
        mock_mx1 = Mock()
        mock_mx1.preference = 20
        mock_mx1.exchange = Mock()
        mock_mx1.exchange.__str__ = Mock(return_value="mx2.local.lets.qa.")

        mock_mx2 = Mock()
        mock_mx2.preference = 10
        mock_mx2.exchange = Mock()
        mock_mx2.exchange.__str__ = Mock(return_value="mx1.local.lets.qa.")

        mock_resolve.return_value = [mock_mx1, mock_mx2]

        result = mx_lookup_all("test@local.lets.qa")

        # Should be sorted by priority
        assert result[0] == "mx1.local.lets.qa"
        assert result[1] == "mx2.local.lets.qa"

    def test_mx_lookup_invalid_email(self):
        """Test MX lookup with invalid email format"""
        with pytest.raises(SystemExit):
            mx_lookup_all("invalid-email")

    @patch("smtpbench.cli.dns.resolver.resolve")
    def test_mx_lookup_no_records(self, mock_resolve):
        """Test MX lookup when no records found"""
        mock_resolve.return_value = []

        with pytest.raises(SystemExit):
            mx_lookup_all("test@local.lets.qa")

    @patch("smtpbench.cli.dns.resolver.resolve")
    def test_mx_lookup_dns_failure(self, mock_resolve):
        """Test MX lookup when DNS query fails"""
        mock_resolve.side_effect = Exception("DNS query failed")

        with pytest.raises(SystemExit):
            mx_lookup_all("test@local.lets.qa")


class TestIntegration:
    """Integration tests for combined functionality"""

    def test_argument_parsing_with_all_options(self):
        """Test parsing all available arguments"""
        sys.argv = [
            "smtpbench",
            "recipient=test@local.lets.qa",
            "port=587",
            "threads=10",
            "messages=100",
            "from_address=sender@local.lets.qa",
            "use_tls=true",
            "retry_delay=5",
            "max_retries=3",
            "debug=true",
            "journal=true",
            "journal_address=archive@local.lets.qa",
        ]

        args = parse_args()

        assert args["recipient"] == "test@local.lets.qa"
        assert args["port"] == "587"
        assert args["threads"] == "10"
        assert args["messages"] == "100"
        assert args["from_address"] == "sender@local.lets.qa"
        assert args["use_tls"] == "true"
        assert args["retry_delay"] == "5"
        assert args["max_retries"] == "3"
        assert args["debug"] == "true"
        assert args["journal"] == "true"
        assert args["journal_address"] == "archive@local.lets.qa"

    def test_json_log_is_valid_json(self):
        """Test that logged output is valid JSON"""
        mock_logger = Mock()

        log_json(
            mock_logger,
            status="success",
            thread_id=1,
            message_id=1,
            duration=1.23,
            mx_host_used="mx.local.lets.qa",
            recipients=["test@local.lets.qa"],
        )

        call_args = mock_logger.info.call_args[0][0]

        # Should not raise an exception
        log_entry = json.loads(call_args)
        assert isinstance(log_entry, dict)


class TestRangeParsing:
    """Test range-aware attachment size and count parsers."""

    def test_parse_size_range_single_value(self):
        from smtpbench.cli import parse_size_range

        assert parse_size_range("512KB") == (512 * 1024, 512 * 1024)

    def test_parse_size_range_span(self):
        from smtpbench.cli import parse_size_range

        assert parse_size_range("10KB-2MB") == (10 * 1024, 2 * 1024 * 1024)

    def test_parse_size_range_rejects_inverted(self):
        from smtpbench.cli import parse_size_range

        with pytest.raises(ValueError):
            parse_size_range("2MB-10KB")

    def test_parse_count_range_single_value(self):
        from smtpbench.cli import parse_count_range

        assert parse_count_range("3") == (3, 3)

    def test_parse_count_range_span(self):
        from smtpbench.cli import parse_count_range

        assert parse_count_range("1-3") == (1, 3)

    def test_parse_count_range_rejects_zero(self):
        from smtpbench.cli import parse_count_range

        with pytest.raises(ValueError):
            parse_count_range("0-2")

    def test_parse_count_range_rejects_inverted(self):
        from smtpbench.cli import parse_count_range

        with pytest.raises(ValueError):
            parse_count_range("5-2")


class TestTLSMode:
    """Test TLS transport mode resolution."""

    def test_default_is_starttls(self):
        from smtpbench.cli import resolve_tls_mode

        assert resolve_tls_mode({}, 587) == "starttls"

    def test_port_465_defaults_to_ssl(self):
        from smtpbench.cli import resolve_tls_mode

        assert resolve_tls_mode({}, 465) == "ssl"

    def test_explicit_mode_overrides_465_default(self):
        from smtpbench.cli import resolve_tls_mode

        assert resolve_tls_mode({"tls_mode": "starttls"}, 465) == "starttls"

    def test_use_tls_alias_true(self):
        from smtpbench.cli import resolve_tls_mode

        assert resolve_tls_mode({"use_tls": "true"}, 587) == "starttls"

    def test_use_tls_alias_false(self):
        from smtpbench.cli import resolve_tls_mode

        assert resolve_tls_mode({"use_tls": "false"}, 587) == "none"

    def test_tls_mode_wins_over_use_tls(self):
        from smtpbench.cli import resolve_tls_mode

        assert resolve_tls_mode({"tls_mode": "none", "use_tls": "true"}, 587) == "none"

    def test_invalid_mode_raises(self):
        from smtpbench.cli import resolve_tls_mode

        with pytest.raises(ValueError):
            resolve_tls_mode({"tls_mode": "bogus"}, 587)


class TestCredentials:
    """Test SMTP credential resolution order and redaction."""

    def test_cli_credentials_win(self, monkeypatch):
        from smtpbench.cli import resolve_credentials

        monkeypatch.setenv("SMTPBENCH_USER", "envuser")
        monkeypatch.setenv("SMTPBENCH_PASS", "envpass")
        user, password, source = resolve_credentials({"username": "cliuser", "password": "clipass"})
        assert (user, password, source) == ("cliuser", "clipass", "cli")

    def test_env_credentials_used_when_no_cli(self, monkeypatch):
        from smtpbench.cli import resolve_credentials

        monkeypatch.setenv("SMTPBENCH_USER", "envuser")
        monkeypatch.setenv("SMTPBENCH_PASS", "envpass")
        user, password, source = resolve_credentials({})
        assert (user, password, source) == ("envuser", "envpass", "env")

    def test_no_credentials(self, monkeypatch):
        from smtpbench.cli import resolve_credentials

        monkeypatch.delenv("SMTPBENCH_USER", raising=False)
        monkeypatch.delenv("SMTPBENCH_PASS", raising=False)
        assert resolve_credentials({}) == (None, None, None)

    def test_partial_cli_credentials_rejected(self, monkeypatch):
        import pytest

        from smtpbench.cli import resolve_credentials

        monkeypatch.delenv("SMTPBENCH_USER", raising=False)
        monkeypatch.delenv("SMTPBENCH_PASS", raising=False)
        with pytest.raises(ValueError, match="username= and password="):
            resolve_credentials({"username": "cliuser"})
        with pytest.raises(ValueError, match="username= and password="):
            resolve_credentials({"password": "clipass"})

    def test_partial_env_credentials_rejected(self, monkeypatch):
        import pytest

        from smtpbench.cli import resolve_credentials

        monkeypatch.setenv("SMTPBENCH_USER", "envuser")
        monkeypatch.delenv("SMTPBENCH_PASS", raising=False)
        with pytest.raises(ValueError, match="SMTPBENCH_USER and SMTPBENCH_PASS"):
            resolve_credentials({})

    def test_login_called_when_username_set(self):
        from unittest.mock import MagicMock

        from smtpbench import cli
        from smtpbench.cli import create_message, try_send_to_mx_hosts

        cli.mx_hosts = ["mx.example.com"]
        cli.auth_username = "user"
        cli.auth_password = "secret"
        fake_server = MagicMock()
        # context manager returns the server itself
        cm = MagicMock()
        cm.__enter__.return_value = fake_server
        cm.__exit__.return_value = False
        with patch("smtplib.SMTP", return_value=cm) as smtp_ctor:
            msg = create_message("to@example.com", "from@example.com", 1, 1, [])
            host, error = try_send_to_mx_hosts(
                "from@example.com", ["to@example.com"], msg, 587, "starttls", 20
            )
        assert error is None
        assert smtp_ctor.called
        fake_server.login.assert_called_once_with("user", "secret")

    def test_login_not_called_without_username(self):
        from unittest.mock import MagicMock

        from smtpbench import cli
        from smtpbench.cli import create_message, try_send_to_mx_hosts

        cli.mx_hosts = ["mx.example.com"]
        cli.auth_username = None
        cli.auth_password = None
        fake_server = MagicMock()
        cm = MagicMock()
        cm.__enter__.return_value = fake_server
        cm.__exit__.return_value = False
        with patch("smtplib.SMTP", return_value=cm):
            msg = create_message("to@example.com", "from@example.com", 1, 1, [])
            try_send_to_mx_hosts("from@example.com", ["to@example.com"], msg, 587, "none", 20)
        fake_server.login.assert_not_called()

    def test_debug_suppressed_around_login(self):
        """When debug is on, wire debug is off during AUTH and restored after.

        Guards the redaction invariant: smtplib's set_debuglevel(1) would print
        the (reversible base64) SASL AUTH exchange to stderr. Order must be
        set_debuglevel(0) -> login(...) -> set_debuglevel(1).
        """
        from unittest.mock import MagicMock, call

        from smtpbench import cli
        from smtpbench.cli import create_message, try_send_to_mx_hosts

        cli.mx_hosts = ["mx.example.com"]
        cli.auth_username = "user"
        cli.auth_password = "secret"
        cli.debug_enabled = True
        cli.debug_logger = MagicMock()
        parent = MagicMock()  # tracks child-call order via method_calls
        fake_server = parent.server
        cm = MagicMock()
        cm.__enter__.return_value = fake_server
        cm.__exit__.return_value = False
        with patch("smtplib.SMTP", return_value=cm):
            msg = create_message("to@example.com", "from@example.com", 1, 1, [])
            host, error = try_send_to_mx_hosts(
                "from@example.com", ["to@example.com"], msg, 587, "none", 20
            )
        assert error is None
        names = [c for c in fake_server.method_calls]
        # The debug-off, login, debug-on triple appears as a contiguous run.
        triple = [
            call.set_debuglevel(0),
            call.login("user", "secret"),
            call.set_debuglevel(1),
        ]
        start = names.index(call.set_debuglevel(0))
        assert names[start : start + 3] == triple


class TestRateLimiter:
    """Test the whole-run token-bucket rate cap."""

    def test_acquire_paces_to_rate(self):
        import time

        from smtpbench.cli import TokenBucket

        bucket = TokenBucket(20)  # 20/sec => ~0.05s apart
        start = time.monotonic()
        for _ in range(5):
            bucket.acquire()
        elapsed = time.monotonic() - start
        # first token is free, remaining 4 paced at ~0.05s => ~0.2s
        assert 0.15 <= elapsed <= 0.8

    def test_first_acquire_is_immediate(self):
        import time

        from smtpbench.cli import TokenBucket

        bucket = TokenBucket(1)
        start = time.monotonic()
        bucket.acquire()
        assert time.monotonic() - start < 0.2


class TestSummary:
    """Test the run summary artifact."""

    def test_compute_percentiles_empty(self):
        from smtpbench.cli import compute_percentiles

        assert compute_percentiles([]) is None

    def test_compute_percentiles_single_sample(self):
        from smtpbench.cli import compute_percentiles

        result = compute_percentiles([0.2])  # 200 ms
        assert result == {"p50": 200, "p95": 200, "p99": 200, "max": 200}

    def test_compute_percentiles_vector(self):
        from smtpbench.cli import compute_percentiles

        samples = [i / 1000 for i in range(1, 101)]  # 1ms..100ms
        result = compute_percentiles(samples)
        assert result["max"] == 100
        assert 45 <= result["p50"] <= 55
        assert result["p95"] >= result["p50"]
        assert result["p99"] >= result["p95"]

    def test_record_result_updates_store(self):
        from smtpbench import cli
        from smtpbench.cli import record_result

        record_result(True, 0.1, "mx1.example.com")
        record_result(False, 0.2, "mx1.example.com")
        assert cli.latency_samples == [0.1]
        assert cli.per_mx_stats["mx1.example.com"] == {"sent": 1, "failed": 1}

    def test_write_summary_produces_valid_json(self, tmp_path):
        from smtpbench import cli
        from smtpbench.cli import write_summary

        cli.log_dir = str(tmp_path)
        cli.retry_count = 2
        cli.latency_samples = [0.1, 0.2, 0.3]
        cli.per_mx_stats = {"mx1": {"sent": 3, "failed": 1}}
        config = {"threads": 2, "messages": 2, "tls_mode": "starttls", "auth": True, "port": 587}
        path = write_summary(config, 12.5)
        with open(path) as f:
            data = json.load(f)
        assert data["run_uuid"] == cli.run_uuid
        assert data["totals"]["sent"] == 3
        assert data["totals"]["failed"] == 1
        assert data["totals"]["retried"] == 2
        assert data["config"]["auth"] is True
        assert "password" not in json.dumps(data)
        assert data["latency_ms"]["max"] == 300
        assert data["per_mx"]["mx1"] == {"sent": 3, "failed": 1}

    def test_write_summary_totals_derive_from_per_mx_not_attempts(self, tmp_path):
        """totals reflect per-message final outcomes, not attempt-level counters.

        A message that failed twice then succeeded leaves fail_count=2 (attempts)
        but per_mx failed=0 (final outcome). The summary must report the
        per-message view so totals and per_mx never disagree.
        """
        from smtpbench import cli
        from smtpbench.cli import write_summary

        cli.log_dir = str(tmp_path)
        # Attempt-level live counters (would inflate 'failed' if used directly).
        cli.success_count = 1
        cli.fail_count = 2
        cli.retry_count = 2
        cli.latency_samples = [0.05]
        # Per-message final outcomes across two hosts.
        cli.per_mx_stats = {
            "mx1": {"sent": 1, "failed": 0},
            "mx2": {"sent": 4, "failed": 1},
        }
        path = write_summary({"auth": False}, 1.0)
        with open(path) as f:
            data = json.load(f)
        assert data["totals"]["sent"] == 5
        assert data["totals"]["failed"] == 1
        assert data["totals"]["retried"] == 2
        assert data["totals"]["success_rate"] == round(5 / 6 * 100, 1)


class TestBodyPlan:
    """Body-text corpus loading and selection."""

    def test_no_body_text_dir_returns_none(self):
        from smtpbench.cli import build_body_plan

        assert build_body_plan({}) is None

    def test_loads_corpus_from_dir(self, tmp_path):
        from smtpbench.cli import build_body_plan

        (tmp_path / "a.txt").write_text("alpha body", encoding="utf-8")
        (tmp_path / "b.txt").write_text("beta body text", encoding="utf-8")
        plan = build_body_plan({"body_text_dir": str(tmp_path)})
        assert plan is not None
        assert len(plan.corpus) == 2
        filenames = sorted(entry["filename"] for entry in plan.corpus)
        assert filenames == ["a.txt", "b.txt"]
        a_entry = next(e for e in plan.corpus if e["filename"] == "a.txt")
        assert a_entry["content"] == "alpha body"
        assert a_entry["char_len"] == len("alpha body")

    def test_missing_dir_raises(self):
        from smtpbench.cli import build_body_plan

        with pytest.raises(NotADirectoryError):
            build_body_plan({"body_text_dir": "/no/such/dir/here"})

    def test_empty_dir_raises(self, tmp_path):
        from smtpbench.cli import build_body_plan

        with pytest.raises(ValueError):
            build_body_plan({"body_text_dir": str(tmp_path)})

    def test_non_utf8_file_handled(self, tmp_path):
        from smtpbench.cli import build_body_plan

        (tmp_path / "bad.txt").write_bytes(b"\xff\xfe valid tail")
        plan = build_body_plan({"body_text_dir": str(tmp_path)})
        assert len(plan.corpus) == 1
        # errors="replace" means the read succeeds and produces a str
        assert isinstance(plan.corpus[0]["content"], str)

    def test_select_returns_corpus_entry(self, tmp_path):
        import random

        from smtpbench.cli import build_body_plan

        (tmp_path / "only.txt").write_text("the one body", encoding="utf-8")
        plan = build_body_plan({"body_text_dir": str(tmp_path)})
        choice = plan.select(random.Random("seed"))
        assert choice["filename"] == "only.txt"
        assert choice["content"] == "the one body"


class TestBodyPrefix:
    """Body-prefix assembly and log metadata."""

    def test_body_prefix_prepended_above_subject_echo(self):
        from smtpbench.cli import create_message

        msg = create_message(
            "to@example.com", "from@example.com", 1, 1, None, body_prefix="EXCERPT TEXT"
        )
        body = msg.get_payload(0).get_payload()
        # excerpt first, blank line, then the subject-echo line
        assert body.startswith("EXCERPT TEXT\n\n")
        assert "Quick test from thread 1 message 1 [" in body
        assert body.rstrip().endswith("https://github.com/SMTPBench/SMTPBench")

    def test_no_body_prefix_leaves_body_unchanged(self):
        from smtpbench.cli import create_message, run_uuid

        msg = create_message("to@example.com", "from@example.com", 2, 3, None)
        body = msg.get_payload(0).get_payload()
        expected = (
            f"Quick test from thread 2 message 3 [{run_uuid}]\n\n"
            "--\nSMTPBench Load Testing Tool\nhttps://github.com/SMTPBench/SMTPBench"
        )
        assert body == expected

    def test_tracking_headers_preserved_with_prefix(self):
        from smtpbench.cli import create_message, run_uuid

        msg = create_message("to@example.com", "from@example.com", 4, 5, None, body_prefix="X")
        assert msg["X-SMTPBench-Run-UUID"] == run_uuid
        assert msg["X-SMTPBench-Thread-ID"] == "4"
        assert msg["X-SMTPBench-Message-ID"] == "5"
        assert msg["Subject"] == f"Quick test from thread 4 message 5 [{run_uuid}]"

    def test_log_json_includes_body_source_metadata(self, mock_logger):
        import json

        from smtpbench.cli import log_json

        log_json(
            mock_logger,
            "success",
            1,
            1,
            0.05,
            body_source={"filename": "a.txt", "char_len": 42},
        )
        entry = json.loads(mock_logger.info.call_args[0][0])
        assert entry["body_source"] == {"filename": "a.txt", "char_len": 42}

    def test_log_json_body_source_defaults_none(self, mock_logger):
        import json

        from smtpbench.cli import log_json

        log_json(mock_logger, "success", 1, 1, 0.05)
        entry = json.loads(mock_logger.info.call_args[0][0])
        assert entry["body_source"] is None


class TestWriteEml:
    """Offline EML serialization and content-addressed naming."""

    def test_writes_file_named_by_sha256(self, tmp_path):
        import hashlib

        from smtpbench.cli import create_message, write_eml

        msg = create_message("to@example.com", "from@example.com", 1, 1)
        digest = write_eml(msg, str(tmp_path))
        expected = hashlib.sha256(msg.as_bytes()).hexdigest()
        assert digest == expected
        written = tmp_path / f"{digest}.eml"
        assert written.is_file()
        assert written.read_bytes() == msg.as_bytes()

    def test_identical_bytes_dedupe_to_one_file(self, tmp_path):
        from email.mime.text import MIMEText

        from smtpbench.cli import write_eml

        # Two messages with identical bytes -> same digest -> one file
        msg_a = MIMEText("same content")
        msg_b = MIMEText("same content")
        d1 = write_eml(msg_a, str(tmp_path))
        d2 = write_eml(msg_b, str(tmp_path))
        assert d1 == d2
        assert len(list(tmp_path.glob("*.eml"))) == 1

    def test_digest_is_64_hex_chars(self, tmp_path):
        from smtpbench.cli import create_message, write_eml

        msg = create_message("to@example.com", "from@example.com", 7, 9)
        digest = write_eml(msg, str(tmp_path))
        assert len(digest) == 64
        assert all(c in "0123456789abcdef" for c in digest)


class TestOfflineMode:
    """Offline EML send fork in send_email."""

    def _make_progress_bar(self):
        from unittest.mock import Mock

        return Mock()

    def test_offline_send_writes_eml_and_counts_success(self, tmp_path, mock_logger):
        from unittest.mock import patch

        from smtpbench import cli

        cli.offline_mode = True
        cli.eml_out_dir = str(tmp_path)
        cli.mx_hosts = []
        loggers = {"success": mock_logger, "fail": mock_logger, "retry": mock_logger}

        with patch("smtpbench.cli.smtplib") as smtplib_mock:
            cli.send_email(
                25,
                "to@example.com",
                "from@example.com",
                1,
                1,
                0,
                loggers,
                "none",
                20,
                3,
                self._make_progress_bar(),
            )
            # offline path must never touch smtplib
            assert not smtplib_mock.SMTP.called
            assert not smtplib_mock.SMTP_SSL.called

        assert cli.success_count == 1
        assert cli.fail_count == 0
        eml_files = list(tmp_path.glob("*.eml"))
        assert len(eml_files) == 1
        assert cli.per_mx_stats.get("file", {}).get("sent") == 1

    def test_offline_send_records_file_host_and_latency(self, tmp_path, mock_logger):
        from smtpbench import cli

        cli.offline_mode = True
        cli.eml_out_dir = str(tmp_path)
        loggers = {"success": mock_logger, "fail": mock_logger, "retry": mock_logger}
        cli.send_email(
            25,
            "to@example.com",
            "from@example.com",
            2,
            2,
            0,
            loggers,
            "none",
            20,
            3,
            self._make_progress_bar(),
        )
        assert "file" in cli.per_mx_stats
        assert len(cli.latency_samples) == 1

    def test_offline_send_failure_counts_and_records(self, tmp_path, mock_logger):
        from unittest.mock import patch

        from smtpbench import cli

        cli.offline_mode = True
        cli.eml_out_dir = str(tmp_path)
        loggers = {"success": mock_logger, "fail": mock_logger, "retry": mock_logger}
        with patch("smtpbench.cli.write_eml", side_effect=OSError("disk full")):
            cli.send_email(
                25,
                "to@example.com",
                "from@example.com",
                3,
                3,
                0,
                loggers,
                "none",
                20,
                3,
                self._make_progress_bar(),
            )
        assert cli.fail_count == 1
        assert cli.success_count == 0
        assert cli.per_mx_stats.get("file", {}).get("failed") == 1


class TestAddressList:
    def test_random_is_deterministic_for_seeded_rng(self):
        import random

        from smtpbench.cli import AddressList

        addrs = ["a@x.com", "b@x.com", "c@x.com"]
        plan = AddressList(addrs, "random")
        rng1 = random.Random("seed-1")
        rng2 = random.Random("seed-1")
        picks1 = [plan.select(rng1) for _ in range(10)]
        picks2 = [plan.select(rng2) for _ in range(10)]
        assert picks1 == picks2
        assert all(p in addrs for p in picks1)

    def test_roundrobin_cycles_evenly_and_wraps(self):
        from smtpbench.cli import AddressList

        addrs = ["a@x.com", "b@x.com", "c@x.com"]
        plan = AddressList(addrs, "roundrobin")
        # RNG is unused in roundrobin mode; pass a dummy.
        picks = [plan.select(rng=None) for _ in range(7)]
        assert picks == [
            "a@x.com",
            "b@x.com",
            "c@x.com",
            "a@x.com",
            "b@x.com",
            "c@x.com",
            "a@x.com",
        ]

    def test_roundrobin_instances_have_independent_counters(self):
        from smtpbench.cli import AddressList

        p1 = AddressList(["a@x.com", "b@x.com"], "roundrobin")
        p2 = AddressList(["c@x.com", "d@x.com"], "roundrobin")
        assert p1.select(None) == "a@x.com"
        assert p2.select(None) == "c@x.com"  # p2 not advanced by p1
        assert p1.select(None) == "b@x.com"
        assert p2.select(None) == "d@x.com"


class TestParseAddressFile:
    def test_parses_one_per_line_skips_blanks_and_comments(self, tmp_path):
        from smtpbench.cli import parse_address_file

        f = tmp_path / "list.txt"
        f.write_text(
            "# primary\n"
            "alice@example.com\n"
            "\n"
            "  bob@example.com  \n"
            "# trailing comment\n"
            "carol@example.com\n"
        )
        assert parse_address_file(str(f), "recipient") == [
            "alice@example.com",
            "bob@example.com",
            "carol@example.com",
        ]

    def test_missing_file_raises(self, tmp_path):
        from smtpbench.cli import parse_address_file

        with pytest.raises(FileNotFoundError):
            parse_address_file(str(tmp_path / "nope.txt"), "recipient")

    def test_empty_after_filtering_raises(self, tmp_path):
        from smtpbench.cli import parse_address_file

        f = tmp_path / "empty.txt"
        f.write_text("# only comments\n\n   \n")
        with pytest.raises(ValueError, match="no valid addresses"):
            parse_address_file(str(f), "from")

    def test_multi_at_address_raises_with_file_and_line(self, tmp_path):
        from smtpbench.cli import parse_address_file

        f = tmp_path / "bad.txt"
        f.write_text("alice@example.com\nbob@@example.com\n")
        with pytest.raises(ValueError, match="line 2"):
            parse_address_file(str(f), "recipient")

    def test_no_at_address_raises(self, tmp_path):
        from smtpbench.cli import parse_address_file

        f = tmp_path / "bad.txt"
        f.write_text("not-an-email\n")
        with pytest.raises(ValueError):
            parse_address_file(str(f), "journal")


class TestBuildAddressList:
    def test_absent_key_returns_none(self):
        from smtpbench.cli import build_address_list

        assert build_address_list({}, "recipient") is None

    def test_builds_with_default_random_order(self, tmp_path):
        from smtpbench.cli import build_address_list

        f = tmp_path / "r.txt"
        f.write_text("a@x.com\nb@x.com\n")
        plan = build_address_list({"recipient_file": str(f)}, "recipient")
        assert plan is not None
        assert plan.order == "random"
        assert plan.addresses == ["a@x.com", "b@x.com"]

    def test_reads_explicit_order(self, tmp_path):
        from smtpbench.cli import build_address_list

        f = tmp_path / "s.txt"
        f.write_text("a@x.com\n")
        plan = build_address_list({"from_file": str(f), "from_file_order": "roundrobin"}, "from")
        assert plan.order == "roundrobin"

    def test_invalid_order_raises(self, tmp_path):
        from smtpbench.cli import build_address_list

        f = tmp_path / "j.txt"
        f.write_text("a@x.com\n")
        with pytest.raises(ValueError, match="roundrobin"):
            build_address_list(
                {"journal_file": str(f), "journal_file_order": "sideways"}, "journal"
            )


class TestAddressListGlobals:
    def test_globals_default_none(self):
        from smtpbench import cli

        assert cli.recipient_list is None
        assert cli.from_list is None
        assert cli.journal_list is None


class TestAddressListValidation:
    def _mk(self, tmp_path, name="l.txt", body="a@x.com\nb@x.com\n"):
        f = tmp_path / name
        f.write_text(body)
        return str(f)

    def test_recipient_file_and_recipient_conflict(self, tmp_path):
        from smtpbench.cli import validate_address_list_args

        args = {"recipient": "x@y.com", "recipient_file": self._mk(tmp_path), "lb_host": "relay"}
        with pytest.raises(ValueError, match="recipient_file"):
            validate_address_list_args(args, offline_mode=False)

    def test_from_file_and_from_address_conflict(self, tmp_path):
        from smtpbench.cli import validate_address_list_args

        args = {"recipient": "x@y.com", "from_file": self._mk(tmp_path), "from_address": "s@y.com"}
        with pytest.raises(ValueError, match="from_file"):
            validate_address_list_args(args, offline_mode=False)

    def test_journal_file_and_journal_address_conflict(self, tmp_path):
        from smtpbench.cli import validate_address_list_args

        args = {
            "recipient": "x@y.com",
            "journal": "true",
            "journal_file": self._mk(tmp_path),
            "journal_address": "j@y.com",
        }
        with pytest.raises(ValueError, match="journal_file"):
            validate_address_list_args(args, offline_mode=False)

    def test_neither_recipient_nor_recipient_file(self, tmp_path):
        from smtpbench.cli import validate_address_list_args

        with pytest.raises(ValueError, match="recipient"):
            validate_address_list_args({}, offline_mode=False)

    def test_recipient_file_requires_lb_host_or_offline(self, tmp_path):
        from smtpbench.cli import validate_address_list_args

        args = {"recipient_file": self._mk(tmp_path)}
        with pytest.raises(ValueError, match="lb_host"):
            validate_address_list_args(args, offline_mode=False)

    def test_recipient_file_ok_with_lb_host(self, tmp_path):
        from smtpbench.cli import validate_address_list_args

        args = {"recipient_file": self._mk(tmp_path), "lb_host": "relay"}
        validate_address_list_args(args, offline_mode=False)  # no raise

    def test_recipient_file_ok_offline_without_lb_host(self, tmp_path):
        from smtpbench.cli import validate_address_list_args

        args = {"recipient_file": self._mk(tmp_path)}
        validate_address_list_args(args, offline_mode=True)  # no raise

    def test_journal_file_requires_journal_true(self, tmp_path):
        from smtpbench.cli import validate_address_list_args

        args = {"recipient": "x@y.com", "journal_file": self._mk(tmp_path)}
        with pytest.raises(ValueError, match="journal=true"):
            validate_address_list_args(args, offline_mode=False)

    def test_orphan_order_key_raises(self, tmp_path):
        from smtpbench.cli import validate_address_list_args

        args = {"recipient": "x@y.com", "from_file_order": "random"}
        with pytest.raises(ValueError, match="from_file_order"):
            validate_address_list_args(args, offline_mode=False)

    def test_journal_true_with_recipient_file_and_no_journal_dest_raises(self, tmp_path):
        """recipient_file + journal=true with no journal_file/journal_address has
        no single recipient to fall back to; validation must fail fast rather
        than silently journal nowhere."""
        from smtpbench.cli import validate_address_list_args

        args = {
            "recipient_file": self._mk(tmp_path),
            "lb_host": "relay",
            "journal": "true",
        }
        with pytest.raises(ValueError, match="journal_address="):
            validate_address_list_args(args, offline_mode=False)

    def test_journal_true_with_recipient_and_no_journal_dest_ok(self, tmp_path):
        """A single recipient= supplies the journal fallback, so journal=true
        without an explicit journal destination is allowed."""
        from smtpbench.cli import validate_address_list_args

        args = {"recipient": "x@y.com", "journal": "true"}
        validate_address_list_args(args, offline_mode=False)  # no raise

    def test_empty_recipient_file_value_raises(self, tmp_path):
        """A present-but-empty recipient_file= is a config error, not an absent
        key: build_address_list must reject it rather than return None."""
        from smtpbench.cli import build_address_list

        with pytest.raises(ValueError, match="empty value"):
            build_address_list({"recipient_file": "   "}, "recipient")


class TestLogJsonAddressFields:
    def test_log_json_includes_from_and_journal_used(self):
        import json
        from unittest.mock import Mock

        from smtpbench.cli import log_json

        logger = Mock()
        log_json(
            logger,
            "success",
            1,
            1,
            0.5,
            from_used="s@x.com",
            journal_used="j@x.com",
        )
        entry = json.loads(logger.info.call_args[0][0])
        assert entry["from_used"] == "s@x.com"
        assert entry["journal_used"] == "j@x.com"

    def test_log_json_address_fields_default_none(self):
        import json
        from unittest.mock import Mock

        from smtpbench.cli import log_json

        logger = Mock()
        log_json(logger, "success", 1, 1, 0.5)
        entry = json.loads(logger.info.call_args[0][0])
        assert entry["from_used"] is None
        assert entry["journal_used"] is None


class TestAddressSelectionInSend:
    def test_effective_addresses_come_from_lists_offline(self, tmp_path):
        """In offline mode, send_email writes an EML whose From/To reflect the
        per-message picks from the address lists."""
        import email

        from smtpbench import cli
        from smtpbench.cli import AddressList

        cli.offline_mode = True
        cli.eml_out_dir = str(tmp_path)
        cli.recipient_list = AddressList(["to@x.com"], "roundrobin")
        cli.from_list = AddressList(["sender@x.com"], "roundrobin")

        from unittest.mock import Mock

        loggers = {"success": Mock(), "fail": Mock(), "retry": Mock(), "debug": Mock()}
        progress = Mock()

        cli.send_email(
            port=587,
            recipient="fallback@x.com",
            from_address="fallback-from@x.com",
            thread_id=1,
            message_id=1,
            retry_delay=0,
            loggers=loggers,
            tls_mode="none",
            transaction_timeout=5,
            max_retries=0,
            progress_bar=progress,
        )

        eml_files = list(tmp_path.glob("*.eml"))
        assert len(eml_files) == 1
        msg = email.message_from_bytes(eml_files[0].read_bytes())
        assert msg["To"] == "to@x.com"
        assert msg["From"] == "sender@x.com"

    def test_random_mode_selection_is_reproducible_across_runs(self, tmp_path):
        """Spec: with all three fields in random mode, a fixed run_uuid +
        thread/message yields the same three picks. This locks the RNG draw
        order (attachments -> body -> recipient -> from -> journal) so adding
        the address draws never perturbs reproducibility."""
        import email
        from unittest.mock import Mock

        from smtpbench import cli
        from smtpbench.cli import AddressList

        def run_once(out_dir):
            cli.offline_mode = True
            cli.eml_out_dir = str(out_dir)
            cli.run_uuid = "fixed-run-uuid"
            cli.journal_enabled = True
            cli.recipient_list = AddressList(["r1@x.com", "r2@x.com", "r3@x.com"], "random")
            cli.from_list = AddressList(["f1@x.com", "f2@x.com"], "random")
            cli.journal_list = AddressList(["j1@x.com", "j2@x.com"], "random")
            loggers = {k: Mock() for k in ("success", "fail", "retry", "debug")}
            cli.send_email(
                port=587,
                recipient="fallback@x.com",
                from_address="fallback-from@x.com",
                thread_id=3,
                message_id=7,
                retry_delay=0,
                loggers=loggers,
                tls_mode="none",
                transaction_timeout=5,
                max_retries=0,
                progress_bar=Mock(),
            )
            eml = list(out_dir.glob("*.eml"))[0]
            m = email.message_from_bytes(eml.read_bytes())
            return (m["To"], m["From"])

        a = tmp_path / "a"
        b = tmp_path / "b"
        a.mkdir()
        b.mkdir()
        assert run_once(a) == run_once(b)


class TestSummaryAddressLists:
    def test_address_lists_summary_reports_metadata_only(self):
        from smtpbench import cli
        from smtpbench.cli import AddressList, address_lists_summary

        cli.recipient_list = AddressList(["a@x.com", "b@x.com"], "roundrobin")
        cli.recipient_list.source = "recipients.txt"
        cli.from_list = AddressList(["s@x.com"], "random")
        cli.from_list.source = "senders.txt"
        cli.journal_list = None

        summary = address_lists_summary()
        assert summary["recipient"] == {"file": "recipients.txt", "count": 2, "order": "roundrobin"}
        assert summary["from"] == {"file": "senders.txt", "count": 1, "order": "random"}
        assert summary["journal"] is None
        # No raw addresses leaked.
        assert "a@x.com" not in json.dumps(summary)


def _fake_smtp(server=None):
    """Return (connection, server) mocks shaped like `smtplib.SMTP(...)`.

    The send path and banner check both use the connection as a context
    manager, so whatever the constructor returns must yield the server from
    __enter__ and must not suppress exceptions on __exit__.
    """
    server = MagicMock() if server is None else server
    connection = MagicMock()
    connection.__enter__.return_value = server
    connection.__exit__.return_value = False
    return connection, server


class TestMXFailover:
    """try_send_to_mx_hosts walks mx_hosts in priority order until one works."""

    def _send(self, tls_mode="none", port=587):
        msg = create_message("to@example.com", "from@example.com", 1, 1, [])
        return try_send_to_mx_hosts("from@example.com", ["to@example.com"], msg, port, tls_mode, 20)

    def test_falls_over_to_second_host_when_connect_fails(self):
        cli.mx_hosts = ["mx1.example.com", "mx2.example.com"]
        good_conn, good_server = _fake_smtp()
        with patch(
            "smtplib.SMTP", side_effect=[ConnectionRefusedError("mx1 down"), good_conn]
        ) as ctor:
            host, error = self._send()

        assert host == "mx2.example.com"
        assert error is None
        assert ctor.call_count == 2
        good_server.sendmail.assert_called_once()

    def test_falls_over_when_sendmail_fails_mid_transaction(self):
        """A failure inside the SMTP transaction must fail over, not just a
        failure to connect."""
        cli.mx_hosts = ["mx1.example.com", "mx2.example.com"]
        bad_conn, bad_server = _fake_smtp()
        bad_server.sendmail.side_effect = smtplib.SMTPDataError(451, b"try again later")
        good_conn, good_server = _fake_smtp()
        with patch("smtplib.SMTP", side_effect=[bad_conn, good_conn]):
            host, error = self._send()

        assert host == "mx2.example.com"
        assert error is None
        bad_server.sendmail.assert_called_once()
        good_server.sendmail.assert_called_once()

    def test_stops_at_first_success_without_trying_later_hosts(self):
        cli.mx_hosts = ["mx1.example.com", "mx2.example.com", "mx3.example.com"]
        good_conn, good_server = _fake_smtp()
        with patch("smtplib.SMTP", side_effect=[good_conn]) as ctor:
            host, error = self._send()

        assert host == "mx1.example.com"
        assert error is None
        assert ctor.call_count == 1
        good_server.sendmail.assert_called_once()

    def test_returns_last_host_and_last_error_when_all_hosts_fail(self):
        cli.mx_hosts = ["mx1.example.com", "mx2.example.com"]
        with patch("smtplib.SMTP", side_effect=[OSError("first failed"), OSError("second failed")]):
            host, error = self._send()

        assert host == "mx2.example.com"
        assert isinstance(error, OSError)
        # The LAST error is reported, not the first one seen.
        assert str(error) == "second failed"

    def test_no_hosts_returns_none_pair_without_connecting(self):
        cli.mx_hosts = []
        with patch("smtplib.SMTP") as ctor:
            host, error = self._send()

        assert (host, error) == (None, None)
        ctor.assert_not_called()

    def test_ssl_mode_uses_smtp_ssl_and_skips_starttls(self):
        cli.mx_hosts = ["mx1.example.com"]
        conn, server = _fake_smtp()
        # Nested rather than parenthesized: the package floor is Python 3.8.
        with patch("smtplib.SMTP_SSL", return_value=conn) as ssl_ctor:
            with patch("smtplib.SMTP") as plain_ctor:
                host, error = self._send(tls_mode="ssl", port=465)

        assert error is None
        ssl_ctor.assert_called_once_with("mx1.example.com", 465, timeout=20)
        plain_ctor.assert_not_called()
        server.starttls.assert_not_called()

    def test_starttls_mode_upgrades_the_connection(self):
        cli.mx_hosts = ["mx1.example.com"]
        conn, server = _fake_smtp()
        with patch("smtplib.SMTP", return_value=conn):
            host, error = self._send(tls_mode="starttls")

        assert error is None
        server.starttls.assert_called_once()

    def test_failover_error_is_recorded_to_debug_log(self):
        cli.mx_hosts = ["mx1.example.com", "mx2.example.com"]
        cli.debug_enabled = True
        cli.debug_logger = MagicMock()
        good_conn, good_server = _fake_smtp()
        with patch("smtplib.SMTP", side_effect=[OSError("mx1 down"), good_conn]):
            host, error = self._send(tls_mode="starttls")

        assert host == "mx2.example.com"
        assert error is None
        logged = " ".join(str(c) for c in cli.debug_logger.debug.call_args_list)
        # Match the failure line itself, not just the host name: the host also
        # appears in the "Attempting connection to" trace, so a bare host match
        # would pass even if the error were never recorded.
        assert "Error sending to mx1.example.com" in logged
        assert "Starting TLS" in logged  # and the retry's TLS upgrade is traced
        good_server.set_debuglevel.assert_called_with(1)


class TestBannerCheck:
    """check_smtp_banner is the pre-flight gate: any problem exits 1."""

    def test_passes_on_250_banner(self, capsys):
        conn, server = _fake_smtp()
        server.ehlo.return_value = (250, b"mx1 ready")
        with patch("smtplib.SMTP", return_value=conn):
            check_smtp_banner("mx1.example.com", 587, "none", 20)

        out = capsys.readouterr().out
        assert "banner check passed" in out
        assert "mx1 ready" in out  # bytes banner decoded for display
        server.starttls.assert_not_called()

    def test_accepts_str_banner(self, capsys):
        """Banners arrive as bytes from smtplib but str must not crash."""
        conn, server = _fake_smtp()
        server.ehlo.return_value = (250, "already a string")
        with patch("smtplib.SMTP", return_value=conn):
            check_smtp_banner("mx1.example.com", 587, "none", 20)

        assert "already a string" in capsys.readouterr().out

    def test_exits_when_ehlo_is_not_250(self, capsys):
        conn, server = _fake_smtp()
        server.ehlo.return_value = (554, b"no service here")
        with patch("smtplib.SMTP", return_value=conn):
            with pytest.raises(SystemExit) as exc:
                check_smtp_banner("mx1.example.com", 587, "none", 20)

        assert exc.value.code == 1
        assert "banner check failed" in capsys.readouterr().out

    def test_exits_when_ehlo_after_starttls_is_not_250(self, capsys):
        conn, server = _fake_smtp()
        server.ehlo.side_effect = [(250, b"ready"), (500, b"broken after tls")]
        with patch("smtplib.SMTP", return_value=conn):
            with pytest.raises(SystemExit) as exc:
                check_smtp_banner("mx1.example.com", 587, "starttls", 20)

        assert exc.value.code == 1
        server.starttls.assert_called_once()
        assert "EHLO after STARTTLS failed" in capsys.readouterr().out

    def test_passes_starttls_when_both_ehlos_are_250(self, capsys):
        conn, server = _fake_smtp()
        server.ehlo.side_effect = [(250, b"ready"), (250, b"ready over tls")]
        with patch("smtplib.SMTP", return_value=conn):
            check_smtp_banner("mx1.example.com", 587, "starttls", 20)

        server.starttls.assert_called_once()
        assert "banner check passed" in capsys.readouterr().out

    def test_exits_when_connection_raises(self, capsys):
        with patch("smtplib.SMTP", side_effect=ConnectionRefusedError("connection refused")):
            with pytest.raises(SystemExit) as exc:
                check_smtp_banner("mx1.example.com", 587, "none", 20)

        assert exc.value.code == 1
        out = capsys.readouterr().out
        assert "banner check failed" in out
        assert "connection refused" in out

    def test_ssl_mode_uses_smtp_ssl(self):
        conn, server = _fake_smtp()
        server.ehlo.return_value = (250, b"ready")
        with patch("smtplib.SMTP_SSL", return_value=conn) as ssl_ctor:
            with patch("smtplib.SMTP") as plain_ctor:
                check_smtp_banner("mx1.example.com", 465, "ssl", 20)

        ssl_ctor.assert_called_once_with("mx1.example.com", 465, timeout=20)
        plain_ctor.assert_not_called()

    def test_bad_banner_exit_is_not_swallowed_by_broad_except(self, capsys):
        """SystemExit must escape the function's `except Exception` handler.

        If it were caught, a bad banner would report failure twice and mask
        which check actually tripped.
        """
        conn, server = _fake_smtp()
        server.ehlo.return_value = (554, b"no service here")
        with patch("smtplib.SMTP", return_value=conn):
            with pytest.raises(SystemExit):
                check_smtp_banner("mx1.example.com", 587, "none", 20)

        assert capsys.readouterr().out.count("banner check failed") == 1

    def test_debug_logging_when_enabled(self, capsys):
        cli.debug_enabled = True
        cli.debug_logger = MagicMock()
        conn, server = _fake_smtp()
        server.ehlo.return_value = (250, b"ready")
        with patch("smtplib.SMTP", return_value=conn):
            check_smtp_banner("mx1.example.com", 587, "none", 20)

        server.set_debuglevel.assert_called_once_with(1)
        assert cli.debug_logger.debug.called

    def test_debug_records_reason_for_each_failure_path(self):
        """Each of the three exit paths writes its reason to the debug log."""
        cases = [
            ("none", [(554, b"no service")], "banner check failed"),
            ("starttls", [(250, b"ready"), (500, b"broken")], "STARTTLS failed"),
        ]
        for tls_mode, ehlo_results, expected in cases:
            cli.debug_enabled = True
            cli.debug_logger = MagicMock()
            conn, server = _fake_smtp()
            server.ehlo.side_effect = ehlo_results
            with patch("smtplib.SMTP", return_value=conn):
                with pytest.raises(SystemExit):
                    check_smtp_banner("mx1.example.com", 587, tls_mode, 20)
            logged = " ".join(str(c) for c in cli.debug_logger.debug.call_args_list)
            assert expected in logged, f"{tls_mode}: missing {expected!r} in debug log"

        # And the exception path.
        cli.debug_enabled = True
        cli.debug_logger = MagicMock()
        with patch("smtplib.SMTP", side_effect=ConnectionRefusedError("refused")):
            with pytest.raises(SystemExit):
                check_smtp_banner("mx1.example.com", 587, "none", 20)
        logged = " ".join(str(c) for c in cli.debug_logger.debug.call_args_list)
        assert "exception" in logged


def _logged(logger):
    """Decode the JSON payloads a mock logger received, in call order."""
    return [json.loads(record.args[0]) for record in logger.info.call_args_list]


class TestSendEmailRetryLoop:
    """The online branch of send_email — the path real users hit.

    Only the offline/EML branch was covered before. The accounting here is
    deliberately asymmetric and easy to break: fail_count counts every failed
    *attempt*, while per_mx_stats records one final outcome per *message*. The
    summary reads per_mx_stats, so a change that conflated the two would
    silently inflate the reported failure count.
    """

    def _send(self, mx_results, max_retries=3, retry_delay=7):
        """Run one send with try_send_to_mx_hosts stubbed out.

        `mx_results` is the (host, error) sequence the stub hands back, one per
        attempt. Returns the mock loggers, the stub, and the sleep mock.
        """
        loggers = {name: MagicMock() for name in ("success", "fail", "retry")}
        with ExitStack() as stack:
            sender = stack.enter_context(
                patch("smtpbench.cli.try_send_to_mx_hosts", side_effect=mx_results)
            )
            sleep = stack.enter_context(patch("time.sleep"))
            send_email(
                587,
                "to@example.com",
                "from@example.com",
                1,
                1,
                retry_delay,
                loggers,
                "none",
                20,
                max_retries,
                MagicMock(),
            )
        return loggers, sender, sleep

    def test_first_attempt_success_records_one_send(self):
        loggers, sender, sleep = self._send([("mx1.example.com", None)])

        assert sender.call_count == 1
        assert (cli.success_count, cli.fail_count, cli.retry_count) == (1, 0, 0)
        assert cli.per_mx_stats == {"mx1.example.com": {"sent": 1, "failed": 0}}
        assert len(cli.latency_samples) == 1
        assert _logged(loggers["success"])[0]["attempt"] == 1
        loggers["fail"].info.assert_not_called()
        loggers["retry"].info.assert_not_called()
        sleep.assert_not_called()

    def test_retry_then_success_counts_one_message_not_three_attempts(self):
        error = smtplib.SMTPServerDisconnected("connection dropped")
        loggers, sender, sleep = self._send(
            [
                ("mx1.example.com", error),
                ("mx1.example.com", error),
                ("mx1.example.com", None),
            ]
        )

        assert sender.call_count == 3
        # Attempt-level counters see all three attempts...
        assert (cli.success_count, cli.fail_count, cli.retry_count) == (1, 2, 2)
        # ...but the summary store records exactly one final outcome.
        assert cli.per_mx_stats == {"mx1.example.com": {"sent": 1, "failed": 0}}
        assert [entry["attempt"] for entry in _logged(loggers["fail"])] == [1, 2]
        assert [entry["retry_number"] for entry in _logged(loggers["retry"])] == [0, 1]
        assert _logged(loggers["success"])[0]["attempt"] == 3
        assert sleep.call_args_list == [call(7), call(7)]

    def test_exhausted_retries_record_one_failure_for_the_message(self):
        error = OSError("connection refused")
        loggers, sender, sleep = self._send([("mx1.example.com", error)] * 3, max_retries=2)

        assert sender.call_count == 3  # the first attempt plus two retries
        assert (cli.success_count, cli.fail_count, cli.retry_count) == (0, 3, 2)
        assert cli.per_mx_stats == {"mx1.example.com": {"sent": 0, "failed": 1}}
        assert cli.latency_samples == []  # latency is sampled on success only
        loggers["success"].info.assert_not_called()
        assert sleep.call_count == 2  # and no sleep after the final attempt

    def test_max_retries_zero_is_a_single_attempt(self):
        loggers, sender, sleep = self._send(
            [("mx1.example.com", OSError("refused"))], max_retries=0
        )

        assert sender.call_count == 1
        assert (cli.fail_count, cli.retry_count) == (1, 0)
        assert cli.per_mx_stats == {"mx1.example.com": {"sent": 0, "failed": 1}}
        loggers["retry"].info.assert_not_called()
        sleep.assert_not_called()

    def test_stop_requested_abandons_retries_without_a_final_outcome(self):
        def fail_then_stop(*_args):
            cli.stop_requested = True
            return "mx1.example.com", OSError("shutting down")

        loggers, sender, _ = self._send(fail_then_stop)

        assert sender.call_count == 1
        assert (cli.fail_count, cli.retry_count) == (1, 1)
        # The stop flag ends the loop before the retry budget runs out, so no
        # final outcome is recorded: the message is abandoned, not failed.
        assert cli.per_mx_stats == {}

    def test_the_host_that_answered_is_the_one_credited(self):
        """The failover result decides the bucket, not the first host tried."""
        loggers, _, _ = self._send([("mx2.example.com", None)])

        assert cli.per_mx_stats == {"mx2.example.com": {"sent": 1, "failed": 0}}
        assert _logged(loggers["success"])[0]["mx_host_used"] == "mx2.example.com"

    def test_journal_address_is_added_to_the_envelope_recipients(self):
        cli.journal_enabled = True
        cli.journal_address = "journal@example.com"

        loggers, _, _ = self._send([("mx1.example.com", None)])

        entry = _logged(loggers["success"])[0]
        assert entry["recipients"] == ["to@example.com", "journal@example.com"]
        assert entry["journal_used"] == "journal@example.com"


def _run_main(argv):
    """Invoke main() with a synthetic argv (the program name is supplied)."""
    with ExitStack() as stack:
        stack.enter_context(patch.object(sys, "argv", ["smtpbench", *argv]))
        # main() installs a SIGINT handler; leave pytest's own handler alone.
        stack.enter_context(patch("smtpbench.cli.signal.signal"))
        main()


def _summary(log_dir):
    """Read back the single summary JSON main() wrote into log_dir."""
    paths = sorted(log_dir.glob("summary_*.json"))
    assert len(paths) == 1, f"expected one summary, found {paths}"
    return json.loads(paths[0].read_text())


class TestMainOffline:
    """main() end to end with no network: the offline/EML branch."""

    def test_offline_run_writes_eml_and_a_consistent_summary(self, tmp_path, capsys):
        eml_dir = tmp_path / "eml"
        log_dir = tmp_path / "logs"

        _run_main(
            [
                "recipient=to@example.com",
                "port=587",
                "threads=2",
                "messages=3",
                f"eml_out_dir={eml_dir}",
                f"logfile_output={log_dir}",
            ]
        )

        stdout = capsys.readouterr().out
        assert "Offline mode" in stdout
        assert "banner check" not in stdout  # offline skips the pre-flight entirely
        assert cli.mx_hosts == []
        assert len(list(eml_dir.glob("*.eml"))) == 6  # 2 threads x 3 messages

        summary = _summary(log_dir)
        assert summary["totals"]["sent"] == 6
        assert summary["totals"]["failed"] == 0
        assert summary["totals"]["success_rate"] == 100.0
        assert summary["per_mx"] == {"file": {"sent": 6, "failed": 0}}
        assert summary["config"]["offline"] is True
        assert summary["config"]["threads"] == 2
        assert summary["config"]["messages"] == 3
        assert summary["config"]["rate"] is None
        assert summary["config"]["auth"] is False
        assert "Total Sent: 6" in stdout

    def test_recipient_file_satisfies_the_recipient_requirement(self, tmp_path):
        address_file = tmp_path / "recipients.txt"
        address_file.write_text("first@example.com\nsecond@example.com\n")
        log_dir = tmp_path / "logs"

        _run_main(
            [
                f"recipient_file={address_file}",
                "port=587",
                "threads=1",
                "messages=2",
                f"eml_out_dir={tmp_path / 'eml'}",
                f"logfile_output={log_dir}",
            ]
        )

        summary = _summary(log_dir)
        recipient_meta = summary["config"]["address_lists"]["recipient"]
        assert recipient_meta["file"] == str(address_file)
        assert recipient_meta["count"] == 2
        # Metadata only: the addresses themselves must never reach the summary.
        assert "first@example.com" not in json.dumps(summary)

    def test_port_is_not_required_offline(self, tmp_path):
        """Offline runs never connect, so port= must not be a required parameter."""
        eml_dir = tmp_path / "eml"
        log_dir = tmp_path / "logs"

        _run_main(
            [
                "recipient=to@example.com",
                "threads=1",
                "messages=2",
                f"eml_out_dir={eml_dir}",
                f"logfile_output={log_dir}",
            ]
        )

        assert len(list(eml_dir.glob("*.eml"))) == 2
        # No connection was made, so there is no port to report.
        assert _summary(log_dir)["config"]["port"] is None

    def test_port_is_still_recorded_offline_when_supplied(self, tmp_path):
        """port= stays accepted offline; it is reported but never used."""
        log_dir = tmp_path / "logs"

        _run_main(
            [
                "recipient=to@example.com",
                "port=587",
                "threads=1",
                "messages=1",
                f"eml_out_dir={tmp_path / 'eml'}",
                f"logfile_output={log_dir}",
            ]
        )

        assert _summary(log_dir)["config"]["port"] == 587

    def test_offline_missing_parameter_message_does_not_demand_port(self, tmp_path, capsys):
        """The required-parameter help must not list port for a run that cannot use it."""
        with pytest.raises(SystemExit) as exc:
            _run_main([f"eml_out_dir={tmp_path / 'eml'}", "recipient=to@example.com"])

        assert exc.value.code == 1
        stdout = capsys.readouterr().out
        assert "threads" in stdout
        assert "messages" in stdout
        assert "• port=NUMBER" not in stdout

    @pytest.mark.parametrize("value", ["", "   "])
    def test_empty_eml_out_dir_is_a_configuration_error(self, value, capsys):
        """A bare eml_out_dir= must not reach os.makedirs("") and traceback."""
        with pytest.raises(SystemExit) as exc:
            _run_main(
                [
                    "recipient=to@example.com",
                    "threads=1",
                    "messages=1",
                    f"eml_out_dir={value}",
                ]
            )

        assert exc.value.code == 1
        assert "eml_out_dir= requires a non-empty directory path" in capsys.readouterr().out


class TestMainOnlineWiring:
    """main()'s online branch: host resolution and the pre-flight gate."""

    def _argv(self, tmp_path, extra=()):
        return [
            "recipient=to@example.com",
            "port=587",
            "threads=1",
            "messages=1",
            "lb_host=relay.example.com",
            f"logfile_output={tmp_path / 'logs'}",
            *extra,
        ]

    def test_lb_host_skips_dns_and_is_the_host_checked_and_used(self, tmp_path, capsys):
        with ExitStack() as stack:
            lookup = stack.enter_context(patch("smtpbench.cli.mx_lookup_all"))
            banner = stack.enter_context(patch("smtpbench.cli.check_smtp_banner"))
            stack.enter_context(
                patch(
                    "smtpbench.cli.try_send_to_mx_hosts",
                    return_value=("relay.example.com", None),
                )
            )
            _run_main(self._argv(tmp_path))

        lookup.assert_not_called()  # a fixed relay means no MX lookup
        assert cli.mx_hosts == ["relay.example.com"]
        banner.assert_called_once_with("relay.example.com", 587, "starttls", 20)

        stdout = capsys.readouterr().out
        assert "TLS mode: starttls" in stdout  # 587 resolves to STARTTLS
        assert "SMTP Hosts Tried: relay.example.com" in stdout
        assert _summary(tmp_path / "logs")["per_mx"] == {
            "relay.example.com": {"sent": 1, "failed": 0}
        }

    def test_banner_failure_aborts_before_any_send(self, tmp_path):
        log_dir = tmp_path / "logs"
        with ExitStack() as stack:
            stack.enter_context(patch("smtpbench.cli.check_smtp_banner", side_effect=SystemExit(1)))
            sender = stack.enter_context(patch("smtpbench.cli.try_send_to_mx_hosts"))
            with pytest.raises(SystemExit) as exc:
                _run_main(self._argv(tmp_path))

        assert exc.value.code == 1
        sender.assert_not_called()  # fail fast: no messages, no summary
        assert list(log_dir.glob("summary_*.json")) == []


class TestMainGuards:
    """main()'s argument guards. Every one of these exits 1 before sending."""

    def _argv(self, tmp_path, extra):
        return [
            "recipient=to@example.com",
            "port=587",
            "threads=1",
            "messages=1",
            "lb_host=relay.example.com",  # keeps DNS out of the guard tests
            f"logfile_output={tmp_path / 'logs'}",
            *extra,
        ]

    def test_missing_required_parameters_are_all_reported(self, capsys):
        with pytest.raises(SystemExit) as exc:
            _run_main(["recipient=to@example.com"])

        assert exc.value.code == 1
        stdout = capsys.readouterr().out
        assert "Missing required parameter(s)" in stdout
        for key in ("port", "threads", "messages"):
            assert key in stdout

    def test_missing_recipient_alone_is_reported(self, capsys):
        with pytest.raises(SystemExit) as exc:
            _run_main(["port=587", "threads=1", "messages=1"])

        assert exc.value.code == 1
        assert "recipient" in capsys.readouterr().out

    @pytest.mark.parametrize("pacing", ["delay=1", "random_delay=true"])
    def test_rate_cannot_be_combined_with_another_pacing_mechanism(self, tmp_path, capsys, pacing):
        with pytest.raises(SystemExit) as exc:
            _run_main(self._argv(tmp_path, ["rate=5", pacing]))

        assert exc.value.code == 1
        assert "rate= cannot be combined" in capsys.readouterr().out

    @pytest.mark.parametrize("value", ["0", "-1", "abc"])
    def test_rate_must_be_a_positive_number(self, tmp_path, capsys, value):
        with pytest.raises(SystemExit) as exc:
            _run_main(self._argv(tmp_path, [f"rate={value}"]))

        assert exc.value.code == 1
        assert "rate must be a positive number" in capsys.readouterr().out

    def test_recipient_file_without_a_fixed_target_is_rejected(self, tmp_path, capsys):
        address_file = tmp_path / "recipients.txt"
        address_file.write_text("first@example.com\n")

        with pytest.raises(SystemExit) as exc:
            _run_main(
                [
                    f"recipient_file={address_file}",
                    "port=587",
                    "threads=1",
                    "messages=1",
                    f"logfile_output={tmp_path / 'logs'}",
                ]
            )

        assert exc.value.code == 1
        stdout = capsys.readouterr().out
        assert "Address list configuration error" in stdout
        # A multi-domain recipient file has no single MX target to resolve.
        assert "requires lb_host=" in stdout

    def test_unreadable_recipient_file_is_reported_as_a_config_error(self, tmp_path, capsys):
        # No recipient= here: recipient_file and recipient are mutually
        # exclusive, and that guard would fire first and mask the missing file.
        with pytest.raises(SystemExit) as exc:
            _run_main(
                [
                    f"recipient_file={tmp_path / 'does-not-exist.txt'}",
                    "port=587",
                    "threads=1",
                    "messages=1",
                    "lb_host=relay.example.com",
                    f"logfile_output={tmp_path / 'logs'}",
                ]
            )

        assert exc.value.code == 1
        assert "Address list configuration error" in capsys.readouterr().out


class TestGlobalStateIsolation:
    """Guards the reset_globals fixture. Keep this class LAST in the file.

    pytest runs tests in declaration order, so a guard only catches pollution
    from tests declared above it. TestCredentials turns cli.debug_enabled on and
    TestSendEmailRetryLoop turns cli.journal_enabled on; neither restores it,
    and before these were added to reset_globals every test that followed ran
    with that state silently applied.
    """

    def test_debug_globals_start_clean(self):
        assert cli.debug_enabled is False
        assert cli.debug_logger is None

    def test_journal_globals_start_clean(self):
        assert cli.journal_enabled is False
        assert cli.journal_address is None

    def test_run_uuid_is_not_the_pinned_one(self):
        """TestAddressSelectionInSend pins run_uuid to seed the per-message RNG.

        Left in place it would change every later test's random draws, so the
        fixture restores the import-time value.
        """
        assert cli.run_uuid != "fixed-run-uuid"

    def test_counters_and_summary_stores_start_clean(self):
        assert (cli.success_count, cli.fail_count, cli.retry_count) == (0, 0, 0)
        assert cli.per_mx_stats == {}
        assert cli.latency_samples == []
        assert cli.stop_requested is False

    def test_file_loggers_have_no_leftover_handlers(self):
        """main() attaches FileHandlers to module-level named loggers."""
        for name in ("success", "fail", "retry", "debug"):
            assert logging.getLogger(name).handlers == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
