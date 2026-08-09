"""Unit tests for SMTPBench"""

import json
import random
import sys
from unittest.mock import Mock, patch

import pytest

from smtpbench.cli import (
    color_rate,
    create_message,
    log_json,
    mx_lookup_all,
    parse_args,
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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
