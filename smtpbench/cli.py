import hashlib
import json
import logging
import mimetypes
import os
import random
import signal
import smtplib
import socket
import statistics
import sys
import threading
import time
import traceback
import uuid
from datetime import datetime
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate

import dns.resolver
from colorama import Fore, Style
from colorama import init as colorama_init
from dotenv import load_dotenv
from tqdm import tqdm

# Import version from package
from . import __version__

# Init colorama for Windows/Linux
colorama_init(autoreset=True)

# Global counters
success_count = 0
fail_count = 0
retry_count = 0
stop_requested = False
lock = threading.Lock()

# Run metadata
run_timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
run_uuid = str(uuid.uuid4())
client_hostname = None
mx_hosts = []  # List of MX hosts in priority order
log_dir = None
journal_enabled = False
journal_address = None
debug_enabled = False
debug_logger = None
attachment_plan = None  # AttachmentPlan or None, built once in main()
body_plan = None  # BodyPlan or None, built once in main()
recipient_list = None  # AddressList or None, built once in main()
from_list = None  # AddressList or None, built once in main()
journal_list = None  # AddressList or None, built once in main()
offline_mode = False  # True when eml_out_dir is set: write EML instead of sending
eml_out_dir = None  # output directory for offline EML files
auth_username = None
auth_password = None
rate_limiter = None  # TokenBucket or None, built in main()
latency_samples = []  # durations (seconds) of successful sends
per_mx_stats = {}  # host -> {"sent": int, "failed": int}

SIZE_UNITS = {
    "B": 1,
    "KB": 1024,
    "K": 1024,
    "MB": 1024 * 1024,
    "M": 1024 * 1024,
}


def show_help():
    """Display help message with all available options."""
    github_url = "https://github.com/SMTPBench/SMTPBench"
    help_text = f"""
{Fore.CYAN}╔══════════════════════════════════════════════════════════════════════════════╗
║                            SMTPBench v{__version__}                              ║
║              SMTP Load Testing and Benchmarking Tool                         ║
║                                                                              ║
║  {Fore.YELLOW}GitHub:{Style.RESET_ALL} {Fore.BLUE}{github_url:<61}{Fore.CYAN} ║
╚══════════════════════════════════════════════════════════════════════════════╝{Style.RESET_ALL}

{Fore.GREEN}USAGE:{Style.RESET_ALL}
    smtpbench [OPTIONS]

{Fore.GREEN}REQUIRED PARAMETERS:{Style.RESET_ALL}
    {Fore.YELLOW}recipient{Style.RESET_ALL}=EMAIL          Target email address
    {Fore.YELLOW}port{Style.RESET_ALL}=NUMBER              SMTP port (25, 587, 465, etc.)
    {Fore.YELLOW}threads{Style.RESET_ALL}=NUMBER           Number of concurrent threads
    {Fore.YELLOW}messages{Style.RESET_ALL}=NUMBER          Messages per thread (0 for infinite)

{Fore.GREEN}OPTIONAL PARAMETERS:{Style.RESET_ALL}
    {Fore.YELLOW}lb_host{Style.RESET_ALL}=HOSTNAME         Load balancer/SMTP host (skips MX lookup)
    {Fore.YELLOW}from_address{Style.RESET_ALL}=EMAIL       Sender email address (default: no-reply@localhost)
    {Fore.YELLOW}tls_mode{Style.RESET_ALL}=MODE             starttls|ssl|none (default: starttls; ssl auto on 465)
    {Fore.YELLOW}use_tls{Style.RESET_ALL}=BOOL             DEPRECATED alias for tls_mode (true→starttls, false→none)
    {Fore.YELLOW}delay{Style.RESET_ALL}=SECONDS            Fixed delay between messages (default: 0)
    {Fore.YELLOW}random_delay{Style.RESET_ALL}=BOOL        Random 1-15 second delay (default: false)
    {Fore.YELLOW}rate{Style.RESET_ALL}=NUMBER              Whole-run cap in messages/sec (excludes delay/random_delay)
    {Fore.YELLOW}retry_delay{Style.RESET_ALL}=SECONDS      Wait time between retries (default: 20)
    {Fore.YELLOW}max_retries{Style.RESET_ALL}=NUMBER       Maximum retry attempts (default: 3)
    {Fore.YELLOW}transaction_timeout{Style.RESET_ALL}=SEC  SMTP timeout in seconds (default: 20)
    {Fore.YELLOW}client_hostname{Style.RESET_ALL}=NAME     Client hostname for HELO/EHLO (default: system)
    {Fore.YELLOW}logfile_output{Style.RESET_ALL}=PATH      Log directory (default: ./logs)
    {Fore.YELLOW}journal{Style.RESET_ALL}=BOOL             Enable journal mode (default: false)
    {Fore.YELLOW}journal_address{Style.RESET_ALL}=EMAIL    Journal recipient (default: same as recipient)
    {Fore.YELLOW}debug{Style.RESET_ALL}=BOOL               Enable debug logging (default: false)
    {Fore.YELLOW}attachment_path{Style.RESET_ALL}=PATH     Attach a specific file to each message
    {Fore.YELLOW}attachment_size{Style.RESET_ALL}=SIZE     Generate synthetic attachment(s), e.g. 512KB, 5MB
    {Fore.YELLOW}attachment_count{Style.RESET_ALL}=NUMBER  Number of generated attachments (default: 1)
    {Fore.YELLOW}attachment_filename{Style.RESET_ALL}=NAME Filename for static/generated attachment(s)
    {Fore.YELLOW}attachment_mime_type{Style.RESET_ALL}=MIME MIME type override for attachment(s)
    {Fore.YELLOW}body_text_dir{Style.RESET_ALL}=PATH       Prefix each body with a random text file from this dir
    {Fore.YELLOW}eml_out_dir{Style.RESET_ALL}=PATH         Offline: write EML files here (sha256-named) instead of sending
    {Fore.YELLOW}username{Style.RESET_ALL}=USER             SMTP AUTH username (prefer env/.env over CLI)
    {Fore.YELLOW}password{Style.RESET_ALL}=PASS             SMTP AUTH password (prefer env/.env over CLI)
    {Fore.YELLOW}dotenv_path{Style.RESET_ALL}=PATH          Path to a .env file (default: auto-discover in cwd or parents)

{Fore.YELLOW}ATTACHMENT SAFETY:{Style.RESET_ALL}
    Attachments multiply outbound volume. SMTPBench prints estimated total
    attachment payload before sending when attachments are enabled.

{Fore.GREEN}EXAMPLES:{Style.RESET_ALL}
    {Fore.CYAN}# Basic test with 5 threads, 10 messages each{Style.RESET_ALL}
    smtpbench recipient=test@example.com port=587 threads=5 messages=10

    {Fore.CYAN}# Test with TLS and custom sender{Style.RESET_ALL}
    smtpbench recipient=test@example.com port=587 \\
              from_address=sender@example.com \\
              threads=10 messages=100 use_tls=true

    {Fore.CYAN}# Test using load balancer instead of MX lookup{Style.RESET_ALL}
    smtpbench recipient=test@example.com lb_host=smtp.example.com \\
              port=587 threads=5 messages=20

    {Fore.CYAN}# High-volume test with retries and timeout{Style.RESET_ALL}
    smtpbench recipient=test@example.com port=587 \\
              threads=100 messages=1000 \\
              retry_delay=10 max_retries=5 \\
              transaction_timeout=30

    {Fore.CYAN}# Continuous load test (infinite messages){Style.RESET_ALL}
    smtpbench recipient=test@example.com port=587 \\
              threads=5 messages=0 random_delay=true

    {Fore.CYAN}# Attach a static file to each message{Style.RESET_ALL}
    smtpbench recipient=test@example.com port=587 \\
              threads=2 messages=5 attachment_path=./sample.pdf

    {Fore.CYAN}# Generate two 1MB synthetic attachments per message{Style.RESET_ALL}
    smtpbench recipient=test@example.com port=587 \\
              threads=2 messages=5 attachment_size=1MB \\
              attachment_count=2 attachment_filename=payload.bin

{Fore.GREEN}OUTPUT:{Style.RESET_ALL}
    • Real-time progress bar with success/fail counts
    • Color-coded success rate (green ≥90%, yellow 70-89%, red <70%)
    • JSON logs: success, fail, retry, debug (when enabled)
    • Each email includes X-SMTPBench-Run-UUID header for tracking

{Fore.GREEN}MORE INFORMATION:{Style.RESET_ALL}
    GitHub:        {Fore.BLUE}https://github.com/SMTPBench/SMTPBench{Style.RESET_ALL}
    Documentation: https://github.com/SMTPBench/SMTPBench#readme
    Issues:        https://github.com/SMTPBench/SMTPBench/issues
    Version:       {__version__}

{Fore.YELLOW}⚠️  WARNING: This tool sends real emails. Ensure you have permission to test.{Style.RESET_ALL}
"""
    print(help_text)
    sys.exit(0)


def parse_args():
    """Parse key=value style arguments into a dictionary."""
    # Check for version flag
    if any(arg.lower() in ["-v", "--version", "version"] for arg in sys.argv[1:]):
        print(
            f"{Fore.CYAN}SMTPBench{Style.RESET_ALL} version {Fore.YELLOW}{__version__}{Style.RESET_ALL}"
        )
        print(f"{Fore.BLUE}https://github.com/SMTPBench/SMTPBench{Style.RESET_ALL}")
        sys.exit(0)

    # Check for help flags
    if len(sys.argv) == 1 or any(
        arg.lower() in ["-h", "--help", "help", "?"] for arg in sys.argv[1:]
    ):
        show_help()

    args = {}
    for arg in sys.argv[1:]:
        if "=" not in arg:
            print(f"{Fore.RED}✗ Invalid argument format: {arg}{Style.RESET_ALL}")
            print(f"{Fore.YELLOW}Expected format: key=value{Style.RESET_ALL}")
            print("\nUse 'smtpbench --help' for usage information.\n")
            sys.exit(1)
        key, value = arg.split("=", 1)
        args[key.strip()] = value.strip()
    return args


def setup_logging():
    """Setup separate JSON loggers for success, fail, retry, and debug."""
    global debug_logger
    loggers = {}
    for name in ["success", "fail", "retry"]:
        filename = os.path.join(log_dir, f"{name}_{run_timestamp}_{run_uuid}.log")
        logger = logging.getLogger(name)
        handler = logging.FileHandler(filename)
        formatter = logging.Formatter("%(message)s")  # raw JSON
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        loggers[name] = logger

    # Debug logger
    debug_filename = os.path.join(log_dir, f"debug_{run_timestamp}_{run_uuid}.log")
    debug_logger = logging.getLogger("debug")
    debug_handler = logging.FileHandler(debug_filename)
    debug_formatter = logging.Formatter("%(asctime)s - %(message)s")
    debug_handler.setFormatter(debug_formatter)
    debug_logger.addHandler(debug_handler)
    debug_logger.setLevel(logging.DEBUG)

    return loggers


def log_json(
    logger,
    status,
    thread_id,
    message_id,
    duration,
    error=None,
    attempt=None,
    retry_number=None,
    mx_host_used=None,
    recipients=None,
    attachments=None,
    body_source=None,
):
    """Log structured JSON for each transaction."""
    entry = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
        "run_uuid": run_uuid,
        "client_hostname": client_hostname,
        "status": status,
        "thread_id": thread_id,
        "message_id": message_id,
        "duration_seconds": round(duration, 3),
        "attempt": attempt,
        "retry_number": retry_number,
        "mx_host_used": mx_host_used,
        "recipients": recipients,
        "attachments": [
            {k: v for k, v in a.items() if k != "content"} for a in (attachments or [])
        ],
        "body_source": body_source,
        "error": str(error) if error else None,
    }
    logger.info(json.dumps(entry))


def mx_lookup_all(recipient):
    """Perform MX lookup for recipient's domain and return all MX hosts sorted by priority."""
    parts = recipient.split("@")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        print(f"Invalid recipient email: {recipient}")
        sys.exit(1)
    domain = parts[1]

    try:
        answers = dns.resolver.resolve(domain, "MX")
        mx_records = sorted(
            [(r.preference, str(r.exchange).rstrip(".")) for r in answers], key=lambda x: x[0]
        )
        if mx_records:
            print(f"[INFO] MX lookup for {domain}:")
            for pref, host in mx_records:
                print(f"  - {host} (priority {pref})")
            return [host for _, host in mx_records]
        else:
            print(f"No MX records found for {domain}")
            sys.exit(1)
    except Exception as e:
        print(f"MX lookup failed for {domain}: {e}")
        sys.exit(1)


def color_rate(rate):
    """Return colored string for success rate."""
    if rate >= 90:
        return Fore.GREEN + f"{rate:.1f}%" + Style.RESET_ALL
    elif rate >= 70:
        return Fore.YELLOW + f"{rate:.1f}%" + Style.RESET_ALL
    else:
        return Fore.RED + f"{rate:.1f}%" + Style.RESET_ALL


def record_result(success, duration, host):
    """Record one send outcome into the summary store (thread-safe)."""
    key = host or "unknown"
    with lock:
        if success:
            latency_samples.append(duration)
        bucket = per_mx_stats.setdefault(key, {"sent": 0, "failed": 0})
        bucket["sent" if success else "failed"] += 1


def compute_percentiles(samples):
    """Return p50/p95/p99/max in milliseconds, or None for an empty list."""
    if not samples:
        return None
    ms = [s * 1000 for s in samples]
    if len(ms) == 1:
        value = round(ms[0])
        return {"p50": value, "p95": value, "p99": value, "max": value}
    cut = statistics.quantiles(ms, n=100, method="inclusive")  # 99 cut points
    return {
        "p50": round(cut[49]),
        "p95": round(cut[94]),
        "p99": round(cut[98]),
        "max": round(max(ms)),
    }


def write_summary(config, elapsed_seconds):
    """Write summary_{timestamp}_{uuid}.json into log_dir; return its path.

    Totals are derived from per_mx_stats (per-message final outcomes) so the
    summary is internally consistent. This differs from the live counters:
    fail_count counts every failed attempt including retries, whereas
    per_mx_stats records one outcome per message. retry_count is reported
    separately as the attempt-level retry total.
    """
    sent = sum(bucket["sent"] for bucket in per_mx_stats.values())
    failed = sum(bucket["failed"] for bucket in per_mx_stats.values())
    total_messages = sent + failed
    success_rate = (sent / total_messages * 100) if total_messages > 0 else 0
    summary = {
        "run_uuid": run_uuid,
        "client_hostname": client_hostname,
        "started_at": run_timestamp,
        "elapsed_seconds": round(elapsed_seconds, 2),
        "config": config,
        "totals": {
            "sent": sent,
            "failed": failed,
            "retried": retry_count,
            "success_rate": round(success_rate, 1),
        },
        "latency_ms": compute_percentiles(latency_samples),
        "per_mx": per_mx_stats,
    }
    path = os.path.join(log_dir, f"summary_{run_timestamp}_{run_uuid}.json")
    with open(path, "w") as summary_file:
        json.dump(summary, summary_file, indent=2)
    return path


def parse_size(size_value):
    """Parse attachment sizes like 1024, 2KB, or 5MB into bytes."""
    value = str(size_value).strip().upper()
    if not value:
        raise ValueError("Attachment size cannot be empty")

    number = ""
    unit = "B"
    for index, character in enumerate(value):
        if character.isdigit():
            number += character
        else:
            unit = value[index:].strip()
            break

    if not number:
        raise ValueError(f"Invalid attachment size: {size_value}")
    if unit not in SIZE_UNITS:
        raise ValueError(f"Unsupported attachment size unit: {unit}")

    return int(number) * SIZE_UNITS[unit]


def parse_size_range(value):
    """Parse an attachment size spec into (min_bytes, max_bytes).

    Accepts a single size ("512KB") or a hyphenated range ("10KB-2MB").
    """
    text = str(value).strip()
    if "-" in text:
        low_text, high_text = text.split("-", 1)
        low = parse_size(low_text)
        high = parse_size(high_text)
    else:
        low = high = parse_size(text)
    if low > high:
        raise ValueError(f"Invalid attachment size range (min > max): {value}")
    return low, high


def parse_count_range(value):
    """Parse an attachment count spec into (min_count, max_count).

    Accepts a single count ("3") or a hyphenated range ("1-3"). Counts are
    integers of at least 1.
    """
    text = str(value).strip()
    try:
        if "-" in text:
            low_text, high_text = text.split("-", 1)
            low = int(low_text)
            high = int(high_text)
        else:
            low = high = int(text)
    except ValueError as exc:
        raise ValueError(f"Invalid attachment count: {value}") from exc
    if low < 1:
        raise ValueError(f"attachment_count must be at least 1: {value}")
    if low > high:
        raise ValueError(f"Invalid attachment count range (min > max): {value}")
    return low, high


class TokenBucket:
    """Thread-safe token bucket enforcing a whole-run messages/sec cap.

    Capacity is one token (no burst), so acquisitions are paced ~1/rate apart
    regardless of thread count.
    """

    def __init__(self, rate):
        self.rate = float(rate)
        self.tokens = 1.0
        self.timestamp = time.monotonic()
        self._bucket_lock = threading.Lock()

    def acquire(self):
        while True:
            with self._bucket_lock:
                now = time.monotonic()
                self.tokens = min(1.0, self.tokens + (now - self.timestamp) * self.rate)
                self.timestamp = now
                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    return
                wait = (1.0 - self.tokens) / self.rate
            time.sleep(wait)


def numbered_filename(filename, index, total):
    """Append a stable counter before a filename extension when needed."""
    if total == 1:
        return filename
    root, extension = os.path.splitext(filename)
    return f"{root}-{index}{extension}"


class AttachmentPlan:
    """Per-message attachment selection for one of three exclusive modes."""

    def __init__(self, mode, *, probability, count_range, filename, mime_type):
        self.mode = mode  # "path" | "size" | "dir"
        self.probability = probability
        self.count_min, self.count_max = count_range
        self.filename = filename
        self.mime_type = mime_type
        # mode-specific payload, populated by build_attachment_plan
        self.static_config = None  # for "path"
        self.size_min = self.size_max = 0  # for "size"
        self.corpus = []  # for "dir": list of config dicts (with content)

    def _mean_count(self):
        return (self.count_min + self.count_max) / 2

    def expected_bytes_per_message(self):
        if self.mode == "path":
            return float(self.static_config["size_bytes"])
        if self.mode == "size":
            mean_size = (self.size_min + self.size_max) / 2
            return self.probability * self._mean_count() * mean_size
        # dir
        mean_size = sum(c["size_bytes"] for c in self.corpus) / len(self.corpus)
        capped_mean_count = min(self._mean_count(), len(self.corpus))
        return self.probability * capped_mean_count * mean_size

    def file_count_label(self):
        if self.mode == "path":
            return "1 static file"
        if self.mode == "size":
            return f"generated, size {self.size_min}-{self.size_max} bytes, count {self.count_min}-{self.count_max}"
        return f"dir corpus of {len(self.corpus)} file(s), count {self.count_min}-{self.count_max}"

    def select_for_message(self, rng):
        """Return the attachment config list for one message (may be empty)."""
        if self.mode == "path":
            return [dict(self.static_config)]

        if rng.random() >= self.probability:
            return []
        count = rng.randint(self.count_min, self.count_max)

        if self.mode == "size":
            configs = []
            for index in range(1, count + 1):
                size_bytes = rng.randint(self.size_min, self.size_max)
                configs.append(
                    {
                        "filename": numbered_filename(self.filename, index, count),
                        "size_bytes": size_bytes,
                        "mime_type": self.mime_type,
                        "source": "generated",
                        "content": b"0" * size_bytes,
                    }
                )
            return configs

        # dir
        count = min(count, len(self.corpus))
        chosen = rng.sample(self.corpus, count)
        return [dict(config) for config in chosen]


def build_attachment_plan(args):
    """Build an AttachmentPlan from CLI args, or None if no attachment args given."""
    attachment_path = args.get("attachment_path")
    attachment_size = args.get("attachment_size")
    attachment_dir = args.get("attachment_dir")

    modes_given = [
        name
        for name, value in (
            ("attachment_path", attachment_path),
            ("attachment_size", attachment_size),
            ("attachment_dir", attachment_dir),
        )
        if value
    ]
    if not modes_given:
        return None
    if len(modes_given) > 1:
        raise ValueError(f"attachment modes are mutually exclusive; got: {', '.join(modes_given)}")

    mime_type_override = args.get("attachment_mime_type")
    probability = float(args.get("attachment_probability", "1.0"))
    if not 0.0 <= probability <= 1.0:
        raise ValueError("attachment_probability must be between 0 and 1")

    if attachment_path:
        if "attachment_count" in args or "attachment_probability" in args:
            raise ValueError(
                "attachment_count/attachment_probability are not supported with attachment_path"
            )
        if not os.path.isfile(attachment_path):
            raise FileNotFoundError(f"Attachment file not found: {attachment_path}")
        filename = args.get("attachment_filename", os.path.basename(attachment_path))
        mime_type = (
            mime_type_override or mimetypes.guess_type(filename)[0] or "application/octet-stream"
        )
        with open(attachment_path, "rb") as attachment_file:
            content = attachment_file.read()
        plan = AttachmentPlan(
            "path", probability=1.0, count_range=(1, 1), filename=filename, mime_type=mime_type
        )
        plan.static_config = {
            "filename": filename,
            "size_bytes": len(content),
            "mime_type": mime_type,
            "source": "file",
            "content": content,
        }
        return plan

    count_range = parse_count_range(args.get("attachment_count", "1"))

    if attachment_size:
        size_min, size_max = parse_size_range(attachment_size)
        base_filename = args.get("attachment_filename", "attachment.bin")
        mime_type = (
            mime_type_override
            or mimetypes.guess_type(base_filename)[0]
            or "application/octet-stream"
        )
        plan = AttachmentPlan(
            "size",
            probability=probability,
            count_range=count_range,
            filename=base_filename,
            mime_type=mime_type,
        )
        plan.size_min, plan.size_max = size_min, size_max
        return plan

    # attachment_dir
    if "attachment_filename" in args:
        raise ValueError(
            "attachment_filename is not supported with attachment_dir; "
            "each file keeps its own corpus name."
        )
    if not os.path.isdir(attachment_dir):
        raise NotADirectoryError(f"Attachment directory not found: {attachment_dir}")
    corpus = []
    for entry in sorted(os.listdir(attachment_dir)):
        full = os.path.join(attachment_dir, entry)
        if not os.path.isfile(full):
            continue
        with open(full, "rb") as corpus_file:
            content = corpus_file.read()
        mime_type = (
            mime_type_override or mimetypes.guess_type(entry)[0] or "application/octet-stream"
        )
        corpus.append(
            {
                "filename": entry,
                "size_bytes": len(content),
                "mime_type": mime_type,
                "source": "dir",
                "content": content,
            }
        )
    if not corpus:
        raise ValueError(f"Attachment directory is empty or unreadable: {attachment_dir}")
    plan = AttachmentPlan(
        "dir",
        probability=probability,
        count_range=count_range,
        filename=None,
        mime_type=mime_type_override,
    )
    plan.corpus = corpus
    return plan


class AddressList:
    """Per-message address selection from a parsed list of addresses.

    order="random":     rng.choice per message (reproducible for a fixed seed).
    order="roundrobin": cycle the list evenly across the whole run; the shared
                        index is guarded by a per-instance lock, so the three
                        address fields' round-robin counters stay independent.
    """

    def __init__(self, addresses, order):
        self.addresses = addresses  # non-empty list[str]
        self.order = order  # "random" | "roundrobin"
        self._idx = 0
        self._lock = threading.Lock()

    def select(self, rng):
        if self.order == "roundrobin":
            with self._lock:
                addr = self.addresses[self._idx % len(self.addresses)]
                self._idx += 1
            return addr
        return rng.choice(self.addresses)


def _is_valid_address(addr):
    """Exactly one '@' with non-empty local and domain parts (the invariant
    mx_lookup_all enforces on the single recipient)."""
    parts = addr.split("@")
    return len(parts) == 2 and bool(parts[0]) and bool(parts[1])


def parse_address_file(path, field_label):
    """Read one address per line. Strip whitespace; skip blank lines and lines
    beginning with '#'. Validate every remaining address (exactly one '@').
    Raise FileNotFoundError if missing, ValueError if no valid addresses remain
    or any address is malformed (message names the file, 1-based line, value)."""
    if not os.path.isfile(path):
        raise FileNotFoundError(f"{field_label} address file not found: {path}")
    addresses = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for lineno, raw in enumerate(fh, start=1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if not _is_valid_address(line):
                raise ValueError(f"Invalid {field_label} address in {path} line {lineno}: {line!r}")
            addresses.append(line)
    if not addresses:
        raise ValueError(f"{field_label} address file has no valid addresses: {path}")
    return addresses


ADDRESS_FILE_ORDERS = ("random", "roundrobin")


def build_address_list(args, field):
    """Build an AddressList for one field ('recipient'|'from'|'journal') from
    '<field>_file' and '<field>_file_order' (default 'random'), or None if the
    '<field>_file' key is absent."""
    path = args.get(f"{field}_file")
    if not path:
        return None
    order = args.get(f"{field}_file_order", "random")
    if order not in ADDRESS_FILE_ORDERS:
        raise ValueError(
            f"Invalid {field}_file_order '{order}'; valid values: {', '.join(ADDRESS_FILE_ORDERS)}"
        )
    addresses = parse_address_file(path, field)
    return AddressList(addresses, order)


def validate_address_list_args(args, offline_mode):
    """Enforce the cross-argument rules for address-list files. Raises
    ValueError on any violation. (Per-file parse errors and invalid order
    values are raised separately by build_address_list/parse_address_file.)"""
    conflicts = [
        ("recipient_file", "recipient"),
        ("from_file", "from_address"),
        ("journal_file", "journal_address"),
    ]
    for file_key, single_key in conflicts:
        if file_key in args and single_key in args:
            raise ValueError(f"{file_key} and {single_key} are mutually exclusive; use one.")

    if "recipient" not in args and "recipient_file" not in args:
        raise ValueError("Provide recipient= or recipient_file=.")

    if "recipient_file" in args and not offline_mode and "lb_host" not in args:
        raise ValueError(
            "recipient_file requires lb_host= (a fixed relay) or eml_out_dir= "
            "(offline output); a multi-domain recipient file has no single MX target."
        )

    if "journal_file" in args and args.get("journal", "false").lower() != "true":
        raise ValueError("journal_file requires journal=true.")

    for field in ("recipient", "from", "journal"):
        if f"{field}_file_order" in args and f"{field}_file" not in args:
            raise ValueError(f"{field}_file_order was given without {field}_file.")


class BodyPlan:
    """Per-message body-prefix selection from a corpus of text files."""

    def __init__(self, corpus):
        self.corpus = corpus  # list of {"filename", "char_len", "content"}

    def select(self, rng):
        """Return one corpus entry chosen uniformly at random."""
        return rng.choice(self.corpus)


def build_body_plan(args):
    """Build a BodyPlan from body_text_dir, or None if the flag is absent.

    Reads every regular file as UTF-8 text (errors="replace" so one bad byte
    never aborts the run). Raises if the directory is missing or yields no files.
    """
    body_text_dir = args.get("body_text_dir")
    if not body_text_dir:
        return None
    if not os.path.isdir(body_text_dir):
        raise NotADirectoryError(f"Body text directory not found: {body_text_dir}")
    corpus = []
    for entry in sorted(os.listdir(body_text_dir)):
        full = os.path.join(body_text_dir, entry)
        if not os.path.isfile(full):
            continue
        with open(full, encoding="utf-8", errors="replace") as body_file:
            content = body_file.read()
        corpus.append({"filename": entry, "char_len": len(content), "content": content})
    if not corpus:
        raise ValueError(f"Body text directory is empty or unreadable: {body_text_dir}")
    return BodyPlan(corpus)


def attachment_metadata(attachment_configs):
    """Return log-safe attachment metadata without raw content bytes."""
    return [
        {
            "filename": config["filename"],
            "size_bytes": config["size_bytes"],
            "mime_type": config["mime_type"],
            "source": config["source"],
        }
        for config in attachment_configs
    ]


def create_message(
    recipient, from_address, thread_id, message_id, attachment_configs=None, body_prefix=None
):
    """Create a tracked SMTPBench MIME message with optional attachments."""
    subject = f"Quick test from thread {thread_id} message {message_id} [{run_uuid}]"
    body = f"{subject}\n\n--\nSMTPBench Load Testing Tool\nhttps://github.com/SMTPBench/SMTPBench"
    if body_prefix is not None:
        body = f"{body_prefix}\n\n{body}"

    msg = MIMEMultipart()
    msg["From"] = from_address
    msg["To"] = recipient
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["X-SMTPBench-Run-UUID"] = run_uuid
    msg["X-SMTPBench-Thread-ID"] = str(thread_id)
    msg["X-SMTPBench-Message-ID"] = str(message_id)
    msg.attach(MIMEText(body, "plain"))

    for config in attachment_configs or []:
        maintype, subtype = config["mime_type"].split("/", 1)
        attachment_part = MIMEBase(maintype, subtype)
        attachment_part.set_payload(config["content"])
        encoders.encode_base64(attachment_part)
        attachment_part.add_header(
            "Content-Disposition",
            "attachment",
            filename=config["filename"],
        )
        msg.attach(attachment_part)

    return msg


def write_eml(msg, out_dir):
    """Serialize msg and write it as {sha256}.eml into out_dir; return the hex digest.

    Content-addressed naming: identical message bytes map to one file (dedup).
    """
    raw = msg.as_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    path = os.path.join(out_dir, f"{digest}.eml")
    with open(path, "wb") as eml_file:
        eml_file.write(raw)
    return digest


TLS_MODES = ("starttls", "ssl", "none")


def resolve_credentials(args):
    """Resolve SMTP credentials. Precedence: CLI > environment (incl. .env).

    Returns (username, password, source) where source is "cli", "env", or None.
    Assumes load_dotenv() has already populated os.environ from any .env file.
    """
    cli_user = args.get("username")
    cli_pass = args.get("password")
    if cli_user or cli_pass:
        if not (cli_user and cli_pass):
            raise ValueError(
                "Both username= and password= must be provided together "
                "(got only one). SMTP AUTH needs a complete credential pair."
            )
        return cli_user, cli_pass, "cli"
    env_user = os.environ.get("SMTPBENCH_USER")
    env_pass = os.environ.get("SMTPBENCH_PASS")
    if env_user or env_pass:
        if not (env_user and env_pass):
            raise ValueError(
                "Both SMTPBENCH_USER and SMTPBENCH_PASS must be set together "
                "(got only one). SMTP AUTH needs a complete credential pair."
            )
        return env_user, env_pass, "env"
    return None, None, None


def resolve_tls_mode(args, port):
    """Resolve the effective TLS transport mode (starttls | ssl | none)."""
    explicit = args.get("tls_mode")
    legacy = args.get("use_tls")

    if explicit is not None:
        mode = explicit.strip().lower()
        if mode not in TLS_MODES:
            raise ValueError(f"Invalid tls_mode '{explicit}'; valid values: {', '.join(TLS_MODES)}")
        if legacy is not None:
            print(f"{Fore.YELLOW}⚠ Both tls_mode and use_tls set; tls_mode wins.{Style.RESET_ALL}")
        return mode

    if legacy is not None:
        print(
            f"{Fore.YELLOW}⚠ use_tls is deprecated; use tls_mode=starttls|ssl|none.{Style.RESET_ALL}"
        )
        return "starttls" if legacy.strip().lower() == "true" else "none"

    return "ssl" if port == 465 else "starttls"


def try_send_to_mx_hosts(from_address, recipients, msg, port, tls_mode, transaction_timeout):
    """Try sending to each MX host in order until one succeeds.

    Returns (host, error). On total failure, host is the last host attempted
    (or None if there were no hosts) and error is the last exception.
    """
    last_error = None
    last_host = None
    for host in mx_hosts:
        last_host = host
        try:
            if debug_enabled:
                debug_logger.debug(f"Attempting connection to MX host: {host}:{port}")
            if tls_mode == "ssl":
                connection = smtplib.SMTP_SSL(host, port, timeout=transaction_timeout)
            else:
                connection = smtplib.SMTP(host, port, timeout=transaction_timeout)
            with connection as server:
                if debug_enabled:
                    server.set_debuglevel(1)
                if tls_mode == "starttls":
                    if debug_enabled:
                        debug_logger.debug("Starting TLS...")
                    server.starttls()
                if auth_username:
                    # Suppress smtplib wire debug around AUTH: set_debuglevel(1)
                    # would print the SASL exchange (base64, trivially reversible)
                    # to stderr, leaking credentials. Restore debug afterward.
                    if debug_enabled:
                        server.set_debuglevel(0)
                    try:
                        server.login(auth_username, auth_password)
                    finally:
                        if debug_enabled:
                            server.set_debuglevel(1)
                if debug_enabled:
                    debug_logger.debug(f"Sending email to recipients: {recipients}")
                server.sendmail(from_address, recipients, msg.as_string())
            return host, None
        except Exception as e:
            last_error = e
            if debug_enabled:
                debug_logger.debug(f"Error sending to {host}: {traceback.format_exc()}")
            continue
    return last_host, last_error


def send_email(
    port,
    recipient,
    from_address,
    thread_id,
    message_id,
    retry_delay,
    loggers,
    tls_mode,
    transaction_timeout,
    max_retries,
    progress_bar,
):
    """Send a single test email, trying all MX hosts if needed."""
    global success_count, fail_count, retry_count, stop_requested, journal_enabled, journal_address

    rng = random.Random(f"{run_uuid}:{thread_id}:{message_id}")
    attachment_configs = attachment_plan.select_for_message(rng) if attachment_plan else []
    body_choice = body_plan.select(rng) if body_plan else None
    body_prefix = body_choice["content"] if body_choice else None
    body_source = (
        {"filename": body_choice["filename"], "char_len": body_choice["char_len"]}
        if body_choice
        else None
    )
    msg = create_message(
        recipient, from_address, thread_id, message_id, attachment_configs, body_prefix
    )
    attachments = attachment_metadata(attachment_configs)

    recipients = [recipient]
    if journal_enabled and journal_address:
        recipients.append(journal_address)

    if offline_mode:
        start_time = time.time()
        try:
            write_eml(msg, eml_out_dir)
            duration = time.time() - start_time
            with lock:
                success_count += 1
                total_attempts = success_count + fail_count
                success_rate = (success_count / total_attempts * 100) if total_attempts > 0 else 0
                progress_bar.set_postfix(
                    Success=success_count, Fail=fail_count, Rate=color_rate(success_rate)
                )
            record_result(True, duration, "file")
            log_json(
                loggers["success"],
                "success",
                thread_id,
                message_id,
                duration,
                attempt=1,
                mx_host_used="file",
                recipients=recipients,
                attachments=attachments,
                body_source=body_source,
            )
        except Exception as e:
            duration = time.time() - start_time
            with lock:
                fail_count += 1
                total_attempts = success_count + fail_count
                success_rate = (success_count / total_attempts * 100) if total_attempts > 0 else 0
                progress_bar.set_postfix(
                    Success=success_count, Fail=fail_count, Rate=color_rate(success_rate)
                )
            record_result(False, duration, "file")
            log_json(
                loggers["fail"],
                "fail",
                thread_id,
                message_id,
                duration,
                error=e,
                attempt=1,
                mx_host_used="file",
                recipients=recipients,
                attachments=attachments,
                body_source=body_source,
            )
        return

    attempt = 0
    while not stop_requested and attempt <= max_retries:
        attempt += 1
        start_time = time.time()
        mx_host_used, error = try_send_to_mx_hosts(
            from_address, recipients, msg, port, tls_mode, transaction_timeout
        )

        if error is None:
            duration = time.time() - start_time
            with lock:
                success_count += 1
                total_attempts = success_count + fail_count
                success_rate = (success_count / total_attempts * 100) if total_attempts > 0 else 0
                progress_bar.set_postfix(
                    Success=success_count, Fail=fail_count, Rate=color_rate(success_rate)
                )
            record_result(True, duration, mx_host_used)
            log_json(
                loggers["success"],
                "success",
                thread_id,
                message_id,
                duration,
                attempt=attempt,
                mx_host_used=mx_host_used,
                recipients=recipients,
                attachments=attachments,
                body_source=body_source,
            )
            return
        else:
            duration = time.time() - start_time
            with lock:
                fail_count += 1
                total_attempts = success_count + fail_count
                success_rate = (success_count / total_attempts * 100) if total_attempts > 0 else 0
                progress_bar.set_postfix(
                    Success=success_count, Fail=fail_count, Rate=color_rate(success_rate)
                )
            log_json(
                loggers["fail"],
                "fail",
                thread_id,
                message_id,
                duration,
                error=error,
                attempt=attempt,
                mx_host_used=mx_host_used,
                recipients=recipients,
                attachments=attachments,
                body_source=body_source,
            )

            if attempt <= max_retries:
                with lock:
                    retry_count += 1
                log_json(
                    loggers["retry"],
                    "retry",
                    thread_id,
                    message_id,
                    duration,
                    error=error,
                    attempt=attempt,
                    retry_number=attempt - 1,
                    mx_host_used=mx_host_used,
                    recipients=recipients,
                    attachments=attachments,
                    body_source=body_source,
                )
                time.sleep(retry_delay)
            else:
                record_result(False, duration, mx_host_used)
                return


def worker(
    port,
    recipient,
    from_address,
    thread_id,
    messages_per_thread,
    retry_delay,
    loggers,
    tls_mode,
    delay,
    random_delay,
    transaction_timeout,
    max_retries,
    progress_bar,
):
    """Worker thread to send multiple messages."""
    message_id = 1
    while not stop_requested:
        if messages_per_thread > 0 and message_id > messages_per_thread:
            break
        if rate_limiter is not None:
            rate_limiter.acquire()
        send_email(
            port,
            recipient,
            from_address,
            thread_id,
            message_id,
            retry_delay,
            loggers,
            tls_mode,
            transaction_timeout,
            max_retries,
            progress_bar,
        )
        progress_bar.update(1)

        message_id += 1
        if random_delay:
            time.sleep(random.randint(1, 15))
        elif delay > 0:
            time.sleep(delay)


def signal_handler(sig, frame):
    """Handle Ctrl+C or stop signal."""
    global stop_requested
    print("\nStop signal received. Finishing current sends...")
    stop_requested = True


def check_smtp_banner(host, port, tls_mode, transaction_timeout):
    """Check SMTP connectivity and banner before starting the test."""
    try:
        if debug_enabled:
            debug_logger.debug(f"Performing SMTP banner check on {host}:{port}")
        if tls_mode == "ssl":
            connection = smtplib.SMTP_SSL(host, port, timeout=transaction_timeout)
        else:
            connection = smtplib.SMTP(host, port, timeout=transaction_timeout)
        with connection as server:
            if debug_enabled:
                server.set_debuglevel(1)
            code, banner = server.ehlo()
            if code != 250:
                print(
                    f"[ERROR] SMTP banner check failed for {host}:{port} - Code: {code}, Banner: {banner}"
                )
                if debug_enabled:
                    debug_logger.debug(f"SMTP banner check failed: Code={code}, Banner={banner}")
                sys.exit(1)
            if tls_mode == "starttls":
                server.starttls()
                code, banner = server.ehlo()
                if code != 250:
                    print(
                        f"[ERROR] SMTP EHLO after STARTTLS failed for {host}:{port} - Code: {code}, Banner: {banner}"
                    )
                    if debug_enabled:
                        debug_logger.debug(
                            f"SMTP EHLO after STARTTLS failed: Code={code}, Banner={banner}"
                        )
                    sys.exit(1)
            print(
                f"[INFO] SMTP banner check passed for {host}:{port} - {banner.decode() if isinstance(banner, bytes) else banner}"
            )
            if debug_enabled:
                debug_logger.debug(f"SMTP banner check passed: {banner}")
    except Exception as e:
        print(f"[ERROR] SMTP banner check failed for {host}:{port} - {e}")
        if debug_enabled:
            debug_logger.debug(f"SMTP banner check exception: {traceback.format_exc()}")
        sys.exit(1)


def main():
    global \
        stop_requested, \
        client_hostname, \
        mx_hosts, \
        log_dir, \
        journal_enabled, \
        journal_address, \
        debug_enabled, \
        attachment_plan, \
        body_plan, \
        recipient_list, \
        from_list, \
        journal_list, \
        offline_mode, \
        eml_out_dir, \
        auth_username, \
        auth_password, \
        rate_limiter
    args = parse_args()
    load_dotenv(dotenv_path=args.get("dotenv_path"))

    required = ["port", "threads", "messages"]
    missing = [key for key in required if key not in args]
    if "recipient" not in args and "recipient_file" not in args:
        missing.append("recipient")
    if missing:
        print(
            f"\n{Fore.RED}✗ Missing required parameter(s): {', '.join(missing)}{Style.RESET_ALL}\n"
        )
        print(f"{Fore.YELLOW}Required parameters:{Style.RESET_ALL}")
        print("  • recipient=EMAIL     - Target email address")
        print("  • port=NUMBER         - SMTP port (25, 587, 465, etc.)")
        print("  • threads=NUMBER      - Number of concurrent threads")
        print("  • messages=NUMBER     - Messages per thread (0 for infinite)")
        print(f"\n{Fore.CYAN}Example:{Style.RESET_ALL}")
        print("  smtpbench recipient=test@example.com port=587 threads=5 messages=10")
        print(f"\n{Fore.CYAN}For full help, run:{Style.RESET_ALL} smtpbench --help\n")
        sys.exit(1)

    log_dir = args.get("logfile_output", "./logs")
    os.makedirs(log_dir, exist_ok=True)

    recipient = args.get("recipient")
    lb_host = args.get("lb_host")
    eml_out_dir = args.get("eml_out_dir")
    offline_mode = eml_out_dir is not None
    if offline_mode:
        os.makedirs(eml_out_dir, exist_ok=True)
        mx_hosts = []
    elif lb_host:
        mx_hosts = [lb_host]
    else:
        mx_hosts = mx_lookup_all(recipient)

    port = int(args["port"])
    from_address = args.get("from_address", "no-reply@localhost")
    threads_count = int(args["threads"])
    messages_per_thread = int(args["messages"])
    retry_delay = int(args.get("retry_delay", 20))
    tls_mode = resolve_tls_mode(args, port)
    delay = int(args.get("delay", 0))
    random_delay = args.get("random_delay", "false").lower() == "true"
    rate = args.get("rate")
    if rate is not None:
        if delay > 0 or random_delay:
            print(
                f"{Fore.RED}✗ rate= cannot be combined with delay= or random_delay=; "
                f"rate is the sole pacing mechanism.{Style.RESET_ALL}"
            )
            sys.exit(1)
        try:
            rate_value = float(rate)
            if rate_value <= 0:
                raise ValueError
        except ValueError:
            print(f"{Fore.RED}✗ rate must be a positive number (messages/sec).{Style.RESET_ALL}")
            sys.exit(1)
        rate_limiter = TokenBucket(rate_value)
        print(f"[INFO] Rate cap: {rate_value} messages/sec (whole run)")
    transaction_timeout = int(args.get("transaction_timeout", 20))
    max_retries = int(args.get("max_retries", 3))
    client_hostname = args.get("client_hostname", socket.gethostname())
    journal_enabled = args.get("journal", "false").lower() == "true"
    journal_address = args.get("journal_address", recipient)
    debug_enabled = args.get("debug", "false").lower() == "true"
    try:
        auth_username, auth_password, cred_source = resolve_credentials(args)
    except ValueError as e:
        print(f"{Fore.RED}✗ Credential configuration error: {e}{Style.RESET_ALL}")
        sys.exit(1)
    if cred_source == "cli":
        print(
            f"{Fore.YELLOW}⚠ Credentials passed on the CLI are visible in ps/top and shell "
            f"history; prefer SMTPBENCH_USER/SMTPBENCH_PASS or a .env file.{Style.RESET_ALL}"
        )
    try:
        attachment_plan = build_attachment_plan(args)
    except Exception as e:
        print(f"{Fore.RED}✗ Attachment configuration error: {e}{Style.RESET_ALL}")
        sys.exit(1)
    try:
        body_plan = build_body_plan(args)
    except Exception as e:
        print(f"{Fore.RED}✗ Body text configuration error: {e}{Style.RESET_ALL}")
        sys.exit(1)

    try:
        validate_address_list_args(args, offline_mode)
        recipient_list = build_address_list(args, "recipient")
        from_list = build_address_list(args, "from")
        journal_list = build_address_list(args, "journal")
    except (ValueError, FileNotFoundError) as e:
        print(f"{Fore.RED}✗ Address list configuration error: {e}{Style.RESET_ALL}")
        sys.exit(1)

    loggers = setup_logging()

    if offline_mode:
        print(f"[INFO] Offline mode: writing EML to {os.path.abspath(eml_out_dir)}")
    else:
        # Print the TLS mode first so it's visible even when the banner check aborts.
        print(f"[INFO] TLS mode: {tls_mode}")
        print(f"[INFO] Performing SMTP banner check on {mx_hosts[0]}:{port}...")
        check_smtp_banner(mx_hosts[0], port, tls_mode, transaction_timeout)

    signal.signal(signal.SIGINT, signal_handler)

    total_messages = threads_count * messages_per_thread if messages_per_thread > 0 else None
    progress_bar = tqdm(total=total_messages, unit="msg", dynamic_ncols=True)

    print(f"[INFO] Run UUID: {run_uuid}")
    print(f"[INFO] Client Hostname: {client_hostname}")
    print(f"[INFO] Authentication: {'enabled' if auth_username else 'disabled'}")
    print(f"[INFO] Logs will be saved in: {os.path.abspath(log_dir)}")
    if journal_enabled:
        print(f"[INFO] Journal mode enabled. Journal address: {journal_address}")
    if debug_enabled:
        print(
            f"[INFO] Debug mode enabled. Debug log: {os.path.join(log_dir, f'debug_{run_timestamp}_{run_uuid}.log')}"
        )
    if attachment_plan:
        expected_per_message = attachment_plan.expected_bytes_per_message()
        estimated_total = (
            f"{int(expected_per_message * total_messages)} bytes (expected)"
            if total_messages
            else "unbounded"
        )
        print(f"[INFO] Attachments enabled: {attachment_plan.file_count_label()}")
        print(
            f"[INFO] Estimated attachment payload: {int(expected_per_message)} bytes/msg; "
            f"total {estimated_total}"
        )

    threads = []
    start_time = time.time()

    for t in range(1, threads_count + 1):
        thread = threading.Thread(
            target=worker,
            args=(
                port,
                recipient,
                from_address,
                t,
                messages_per_thread,
                retry_delay,
                loggers,
                tls_mode,
                delay,
                random_delay,
                transaction_timeout,
                max_retries,
                progress_bar,
            ),
        )
        threads.append(thread)
        thread.start()

    for thread in threads:
        thread.join()

    elapsed = time.time() - start_time
    progress_bar.close()

    print("\n=== SMTP Load Test Summary ===")
    print(f"Run UUID: {run_uuid}")
    print(f"Client Hostname: {client_hostname}")
    if offline_mode:
        print("SMTP Hosts Tried: (offline — wrote EML files)")
    else:
        print(f"SMTP Hosts Tried: {', '.join(mx_hosts)}")
    # Report per-message final outcomes (consistent with the summary JSON and
    # per_mx). fail_count is attempt-level (counts retries); retry_count is
    # surfaced separately below.
    total_sent = sum(bucket["sent"] for bucket in per_mx_stats.values())
    total_failed = sum(bucket["failed"] for bucket in per_mx_stats.values())
    print(f"Total Sent: {total_sent}")
    print(f"Total Failed: {total_failed}")
    print(f"Total Retried: {retry_count}")
    print(f"Elapsed Time: {elapsed:.2f} seconds")
    print(f"Logs saved in: {os.path.abspath(log_dir)}")

    summary_config = {
        "threads": threads_count,
        "messages": messages_per_thread,
        "rate": float(args["rate"]) if args.get("rate") else None,
        "tls_mode": tls_mode,
        "auth": auth_username is not None,
        "port": port,
        "offline": offline_mode,
        "body_text_dir": body_plan is not None,
    }
    summary_path = write_summary(summary_config, elapsed)
    print(f"Summary written to: {summary_path}")


if __name__ == "__main__":
    if len(sys.argv) < 5:
        print(
            "Usage: python smtp_load_test.py recipient=<email> port=<port> threads=<n> messages=<n> "
            "[lb_host=<host>] [from_address=<email>] [retry_delay=<sec>] [use_tls=true|false] [delay=<sec>] "
            "[random_delay=true|false] [transaction_timeout=<sec>] [max_retries=<n>] [client_hostname=<name>] "
            "[logfile_output=<dir>] [journal=true|false] [journal_address=<email>] [debug=true|false] "
            "[attachment_path=<path>|attachment_size=<size>] [attachment_count=<n>] "
            "[attachment_filename=<name>] [attachment_mime_type=<mime>] "
            "[username=<user>] [password=<pass>] [dotenv_path=<path>] [rate=<msgs/sec>] "
            "[body_text_dir=<dir>] [eml_out_dir=<dir>]"
        )
        sys.exit(1)
    main()
