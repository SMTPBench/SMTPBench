import smtplib
import threading
import sys
import time
import logging
import signal
import json
import random
import dns.resolver
import uuid
import socket
import os
import traceback
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from tqdm import tqdm
from datetime import datetime
from colorama import Fore, Style, init as colorama_init

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
    {Fore.YELLOW}use_tls{Style.RESET_ALL}=BOOL             Enable TLS/STARTTLS (default: true)
    {Fore.YELLOW}delay{Style.RESET_ALL}=SECONDS            Fixed delay between messages (default: 0)
    {Fore.YELLOW}random_delay{Style.RESET_ALL}=BOOL        Random 1-15 second delay (default: false)
    {Fore.YELLOW}retry_delay{Style.RESET_ALL}=SECONDS      Wait time between retries (default: 20)
    {Fore.YELLOW}max_retries{Style.RESET_ALL}=NUMBER       Maximum retry attempts (default: 3)
    {Fore.YELLOW}transaction_timeout{Style.RESET_ALL}=SEC  SMTP timeout in seconds (default: 20)
    {Fore.YELLOW}client_hostname{Style.RESET_ALL}=NAME     Client hostname for HELO/EHLO (default: system)
    {Fore.YELLOW}logfile_output{Style.RESET_ALL}=PATH      Log directory (default: ./logs)
    {Fore.YELLOW}journal{Style.RESET_ALL}=BOOL             Enable journal mode (default: false)
    {Fore.YELLOW}journal_address{Style.RESET_ALL}=EMAIL    Journal recipient (default: same as recipient)
    {Fore.YELLOW}debug{Style.RESET_ALL}=BOOL               Enable debug logging (default: false)

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
    if any(arg.lower() in ['-v', '--version', 'version'] for arg in sys.argv[1:]):
        print(f"{Fore.CYAN}SMTPBench{Style.RESET_ALL} version {Fore.YELLOW}{__version__}{Style.RESET_ALL}")
        print(f"{Fore.BLUE}https://github.com/SMTPBench/SMTPBench{Style.RESET_ALL}")
        sys.exit(0)
    
    # Check for help flags
    if len(sys.argv) == 1 or any(arg.lower() in ['-h', '--help', 'help', '?'] for arg in sys.argv[1:]):
        show_help()
    
    args = {}
    for arg in sys.argv[1:]:
        if "=" not in arg:
            print(f"{Fore.RED}✗ Invalid argument format: {arg}{Style.RESET_ALL}")
            print(f"{Fore.YELLOW}Expected format: key=value{Style.RESET_ALL}")
            print(f"\nUse 'smtpbench --help' for usage information.\n")
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
        formatter = logging.Formatter('%(message)s')  # raw JSON
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        loggers[name] = logger

    # Debug logger
    debug_filename = os.path.join(log_dir, f"debug_{run_timestamp}_{run_uuid}.log")
    debug_logger = logging.getLogger("debug")
    debug_handler = logging.FileHandler(debug_filename)
    debug_formatter = logging.Formatter('%(asctime)s - %(message)s')
    debug_handler.setFormatter(debug_formatter)
    debug_logger.addHandler(debug_handler)
    debug_logger.setLevel(logging.DEBUG)

    return loggers

def log_json(logger, status, thread_id, message_id, duration, error=None, attempt=None, retry_number=None, mx_host_used=None, recipients=None):
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
        "error": str(error) if error else None
    }
    logger.info(json.dumps(entry))

def mx_lookup_all(recipient):
    """Perform MX lookup for recipient's domain and return all MX hosts sorted by priority."""
    try:
        domain = recipient.split("@")[1]
    except IndexError:
        print(f"Invalid recipient email: {recipient}")
        sys.exit(1)

    try:
        answers = dns.resolver.resolve(domain, 'MX')
        mx_records = sorted([(r.preference, str(r.exchange).rstrip('.')) for r in answers], key=lambda x: x[0])
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

def try_send_to_mx_hosts(from_address, recipients, msg, port, use_tls, transaction_timeout):
    """Try sending to each MX host in order until one succeeds."""
    last_error = None
    for host in mx_hosts:
        try:
            if debug_enabled:
                debug_logger.debug(f"Attempting connection to MX host: {host}:{port}")
            with smtplib.SMTP(host, port, timeout=transaction_timeout) as server:
                if debug_enabled:
                    server.set_debuglevel(1)  # Enable smtplib debug output
                if use_tls:
                    if debug_enabled:
                        debug_logger.debug("Starting TLS...")
                    server.starttls()
                if debug_enabled:
                    debug_logger.debug(f"Sending email to recipients: {recipients}")
                server.sendmail(from_address, recipients, msg.as_string())
            return host, None  # Success
        except Exception as e:
            last_error = e
            if debug_enabled:
                debug_logger.debug(f"Error sending to {host}: {traceback.format_exc()}")
            continue
    return None, last_error  # All MX hosts failed

def send_email(port, recipient, from_address, thread_id, message_id, retry_delay, loggers, use_tls, transaction_timeout, max_retries, progress_bar):
    """Send a single test email, trying all MX hosts if needed."""
    global success_count, fail_count, retry_count, stop_requested, journal_enabled, journal_address

    subject = f"Quick test from thread {thread_id} message {message_id} [{run_uuid}]"
    body = f"{subject}\n\n--\nSMTPBench Load Testing Tool\nhttps://github.com/SMTPBench/SMTPBench"

    msg = MIMEMultipart()
    msg['From'] = from_address
    msg['To'] = recipient
    msg['Subject'] = subject
    msg['X-SMTPBench-Run-UUID'] = run_uuid
    msg['X-SMTPBench-Thread-ID'] = str(thread_id)
    msg['X-SMTPBench-Message-ID'] = str(message_id)
    msg.attach(MIMEText(body, 'plain'))

    recipients = [recipient]
    if journal_enabled and journal_address:
        recipients.append(journal_address)

    attempt = 0
    while not stop_requested and attempt <= max_retries:
        attempt += 1
        start_time = time.time()
        mx_host_used, error = try_send_to_mx_hosts(from_address, recipients, msg, port, use_tls, transaction_timeout)

        if error is None:
            duration = time.time() - start_time
            with lock:
                success_count += 1
                total_attempts = success_count + fail_count
                success_rate = (success_count / total_attempts * 100) if total_attempts > 0 else 0
                progress_bar.set_postfix(Success=success_count, Fail=fail_count, Rate=color_rate(success_rate))
            log_json(loggers["success"], "success", thread_id, message_id, duration, attempt=attempt, mx_host_used=mx_host_used, recipients=recipients)
            return
        else:
            duration = time.time() - start_time
            with lock:
                fail_count += 1
                total_attempts = success_count + fail_count
                success_rate = (success_count / total_attempts * 100) if total_attempts > 0 else 0
                progress_bar.set_postfix(Success=success_count, Fail=fail_count, Rate=color_rate(success_rate))
            log_json(loggers["fail"], "fail", thread_id, message_id, duration, error=error, attempt=attempt, mx_host_used=mx_host_used, recipients=recipients)

            if attempt <= max_retries:
                with lock:
                    retry_count += 1
                log_json(loggers["retry"], "retry", thread_id, message_id, duration, error=error, attempt=attempt, retry_number=attempt-1, mx_host_used=mx_host_used, recipients=recipients)
                time.sleep(retry_delay)
            else:
                return

def worker(port, recipient, from_address, thread_id, messages_per_thread, retry_delay, loggers, use_tls, delay, random_delay, transaction_timeout, max_retries, progress_bar):
    """Worker thread to send multiple messages."""
    message_id = 1
    while not stop_requested:
        if messages_per_thread > 0 and message_id > messages_per_thread:
            break
        send_email(port, recipient, from_address, thread_id, message_id, retry_delay, loggers, use_tls, transaction_timeout, max_retries, progress_bar)
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

def check_smtp_banner(host, port, use_tls, transaction_timeout):
    """Check SMTP connectivity and banner before starting the test."""
    try:
        if debug_enabled:
            debug_logger.debug(f"Performing SMTP banner check on {host}:{port}")
        with smtplib.SMTP(host, port, timeout=transaction_timeout) as server:
            if debug_enabled:
                server.set_debuglevel(1)
            code, banner = server.ehlo()
            if code != 250:
                print(f"[ERROR] SMTP banner check failed for {host}:{port} - Code: {code}, Banner: {banner}")
                if debug_enabled:
                    debug_logger.debug(f"SMTP banner check failed: Code={code}, Banner={banner}")
                sys.exit(1)
            if use_tls:
                server.starttls()
                code, banner = server.ehlo()
                if code != 250:
                    print(f"[ERROR] SMTP EHLO after STARTTLS failed for {host}:{port} - Code: {code}, Banner: {banner}")
                    if debug_enabled:
                        debug_logger.debug(f"SMTP EHLO after STARTTLS failed: Code={code}, Banner={banner}")
                    sys.exit(1)
            print(f"[INFO] SMTP banner check passed for {host}:{port} - {banner.decode() if isinstance(banner, bytes) else banner}")
            if debug_enabled:
                debug_logger.debug(f"SMTP banner check passed: {banner}")
    except Exception as e:
        print(f"[ERROR] SMTP banner check failed for {host}:{port} - {e}")
        if debug_enabled:
            debug_logger.debug(f"SMTP banner check exception: {traceback.format_exc()}")
        sys.exit(1)

def main():
    global stop_requested, client_hostname, mx_hosts, log_dir, journal_enabled, journal_address, debug_enabled
    args = parse_args()

    required = ["recipient", "port", "threads", "messages"]
    missing = [key for key in required if key not in args]
    if missing:
        print(f"\n{Fore.RED}✗ Missing required parameter(s): {', '.join(missing)}{Style.RESET_ALL}\n")
        print(f"{Fore.YELLOW}Required parameters:{Style.RESET_ALL}")
        print(f"  • recipient=EMAIL     - Target email address")
        print(f"  • port=NUMBER         - SMTP port (25, 587, 465, etc.)")
        print(f"  • threads=NUMBER      - Number of concurrent threads")
        print(f"  • messages=NUMBER     - Messages per thread (0 for infinite)")
        print(f"\n{Fore.CYAN}Example:{Style.RESET_ALL}")
        print(f"  smtpbench recipient=test@example.com port=587 threads=5 messages=10")
        print(f"\n{Fore.CYAN}For full help, run:{Style.RESET_ALL} smtpbench --help\n")
        sys.exit(1)

    log_dir = args.get("logfile_output", "./logs")
    os.makedirs(log_dir, exist_ok=True)

    recipient = args["recipient"]
    lb_host = args.get("lb_host")
    if lb_host:
        mx_hosts = [lb_host]
    else:
        mx_hosts = mx_lookup_all(recipient)

    port = int(args["port"])
    from_address = args.get("from_address", "no-reply@localhost")
    threads_count = int(args["threads"])
    messages_per_thread = int(args["messages"])
    retry_delay = int(args.get("retry_delay", 20))
    use_tls = args.get("use_tls", "true").lower() == "true"
    delay = int(args.get("delay", 0))
    random_delay = args.get("random_delay", "false").lower() == "true"
    transaction_timeout = int(args.get("transaction_timeout", 20))
    max_retries = int(args.get("max_retries", 3))
    client_hostname = args.get("client_hostname", socket.gethostname())
    journal_enabled = args.get("journal", "false").lower() == "true"
    journal_address = args.get("journal_address", recipient)
    debug_enabled = args.get("debug", "false").lower() == "true"

    loggers = setup_logging()

    # Pre-flight SMTP banner check on first MX host
    print(f"[INFO] Performing SMTP banner check on {mx_hosts[0]}:{port}...")
    check_smtp_banner(mx_hosts[0], port, use_tls, transaction_timeout)

    signal.signal(signal.SIGINT, signal_handler)

    total_messages = threads_count * messages_per_thread if messages_per_thread > 0 else None
    progress_bar = tqdm(total=total_messages, unit="msg", dynamic_ncols=True)

    print(f"[INFO] Run UUID: {run_uuid}")
    print(f"[INFO] Client Hostname: {client_hostname}")
    print(f"[INFO] Logs will be saved in: {os.path.abspath(log_dir)}")
    if journal_enabled:
        print(f"[INFO] Journal mode enabled. Journal address: {journal_address}")
    if debug_enabled:
        print(f"[INFO] Debug mode enabled. Debug log: {os.path.join(log_dir, f'debug_{run_timestamp}_{run_uuid}.log')}")

    threads = []
    start_time = time.time()

    for t in range(1, threads_count + 1):
        thread = threading.Thread(
            target=worker,
            args=(port, recipient, from_address, t, messages_per_thread, retry_delay, loggers, use_tls, delay, random_delay, transaction_timeout, max_retries, progress_bar)
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
    print(f"SMTP Hosts Tried: {', '.join(mx_hosts)}")
    print(f"Total Sent: {success_count}")
    print(f"Total Failed: {fail_count}")
    print(f"Total Retried: {retry_count}")
    print(f"Elapsed Time: {elapsed:.2f} seconds")
    print(f"Logs saved in: {os.path.abspath(log_dir)}")

if __name__ == "__main__":
    if len(sys.argv) < 5:
        print("Usage: python smtp_load_test.py recipient=<email> port=<port> threads=<n> messages=<n> "
              "[lb_host=<host>] [from_address=<email>] [retry_delay=<sec>] [use_tls=true|false] [delay=<sec>] "
              "[random_delay=true|false] [transaction_timeout=<sec>] [max_retries=<n>] [client_hostname=<name>] "
              "[logfile_output=<dir>] [journal=true|false] [journal_address=<email>] [debug=true|false]")
        sys.exit(1)
    main()
