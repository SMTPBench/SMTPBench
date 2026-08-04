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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
