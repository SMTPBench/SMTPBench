"""Unit tests for SMTPBench"""

import json
import sys
from unittest.mock import Mock, patch

import pytest

from smtpbench.cli import (
    build_attachment_configs,
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

    def test_build_attachment_configs_for_static_file(self, tmp_path):
        """Static attachment files are captured with name, size, MIME type, and bytes."""
        attachment = tmp_path / "sample.txt"
        attachment.write_text("hello attachment", encoding="utf-8")

        configs = build_attachment_configs({"attachment_path": str(attachment)})

        assert len(configs) == 1
        assert configs[0]["filename"] == "sample.txt"
        assert configs[0]["size_bytes"] == len("hello attachment")
        assert configs[0]["mime_type"] == "text/plain"
        assert configs[0]["source"] == "file"
        assert configs[0]["content"] == b"hello attachment"

    def test_build_attachment_configs_generates_requested_size(self):
        """Synthetic attachments are generated at the requested size."""
        configs = build_attachment_configs(
            {
                "attachment_size": "2KB",
                "attachment_count": "2",
                "attachment_filename": "payload.bin",
                "attachment_mime_type": "application/octet-stream",
            }
        )

        assert len(configs) == 2
        assert [config["filename"] for config in configs] == ["payload-1.bin", "payload-2.bin"]
        assert all(config["size_bytes"] == 2048 for config in configs)
        assert all(config["mime_type"] == "application/octet-stream" for config in configs)
        assert all(config["source"] == "generated" for config in configs)
        assert all(len(config["content"]) == 2048 for config in configs)

    def test_create_message_attaches_files_and_preserves_tracking_headers(self, tmp_path):
        """Attachment-enabled messages remain multipart and keep SMTPBench headers."""
        attachment = tmp_path / "evidence.txt"
        attachment.write_text("payload", encoding="utf-8")
        attachment_configs = build_attachment_configs({"attachment_path": str(attachment)})

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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
