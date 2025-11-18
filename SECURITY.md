# Security Policy

## Supported Versions

We actively support the following versions of SMTPBench with security updates:

| Version | Supported          |
| ------- | ------------------ |
| 1.1.x   | :white_check_mark: |
| 1.0.x   | :white_check_mark: |
| < 1.0   | :x:                |

## Reporting a Vulnerability

We take the security of SMTPBench seriously. If you discover a security vulnerability, please follow these steps:

### How to Report

**Please do NOT report security vulnerabilities through public GitHub issues.**

Instead, please report security vulnerabilities by emailing:

**rmorse@lets.qa**

Include the following information in your report:

- Type of vulnerability
- Full paths of source file(s) related to the vulnerability
- Location of the affected source code (tag/branch/commit or direct URL)
- Step-by-step instructions to reproduce the issue
- Proof-of-concept or exploit code (if possible)
- Impact of the vulnerability, including how an attacker might exploit it

### What to Expect

- **Acknowledgment**: We will acknowledge receipt of your vulnerability report within 48 hours.
- **Updates**: We will provide regular updates (at least every 7 days) on our progress.
- **Timeline**: We aim to release a fix within 30 days of the initial report.
- **Credit**: With your permission, we will credit you in the security advisory and release notes.

## Security Considerations for SMTPBench

### Safe Usage Guidelines

SMTPBench is a load testing tool designed for testing SMTP servers. To use it securely:

1. **Never use production credentials** - Use test accounts and test SMTP servers only
2. **Avoid public networks** - Run tests in isolated, controlled environments
3. **Rate limiting** - Be mindful of the load you generate; excessive testing can be considered abuse
4. **Authentication** - If testing with authentication, ensure credentials are stored securely
5. **Logging** - Be aware that logs may contain sensitive information like email addresses and server details

### Known Security Considerations

- **Plaintext credentials**: SMTPBench accepts SMTP credentials as command-line arguments, which may be visible in process listings. Use environment variables or configuration files with restricted permissions when possible.
- **Log files**: JSON logs contain detailed transaction information. Ensure log files are stored with appropriate permissions (recommended: 600 or 640).
- **TLS/SSL**: When using `use_tls=true`, certificate validation is performed. For testing purposes with self-signed certificates, you may need to adjust your test environment.

### Best Practices

1. **Restrict access** to systems where SMTPBench is installed
2. **Use test environments** separate from production
3. **Rotate test credentials** regularly
4. **Monitor logs** for unauthorized access attempts
5. **Keep updated** to the latest version for security patches

## Security Updates

Security updates will be released as:
- Patch versions (e.g., 1.1.1) for minor security fixes
- Minor versions (e.g., 1.2.0) for security enhancements
- Documented in CHANGELOG.md with `[SECURITY]` prefix

## Scope

### In Scope

- Authentication bypass vulnerabilities
- Code injection vulnerabilities
- Information disclosure issues
- Denial of Service (DoS) vulnerabilities in SMTPBench itself

### Out of Scope

- Vulnerabilities in third-party dependencies (please report to the respective projects)
- Social engineering attacks
- Physical access attacks
- Issues in test SMTP servers (not part of SMTPBench)
- Load testing impacts on target servers (this is the intended purpose)

## Vulnerability Disclosure Policy

We follow a coordinated vulnerability disclosure process:

1. Security researcher reports vulnerability privately
2. We confirm the vulnerability and develop a fix
3. We release a security update
4. We publish a security advisory
5. Public disclosure (30 days after patch release, or by mutual agreement)

## Contact

For security concerns: rmorse@lets.qa

For general support: [GitHub Issues](https://github.com/SMTPBench/SMTPBench/issues)

## Recognition

We appreciate the security research community's efforts in keeping SMTPBench secure. Researchers who report valid vulnerabilities will be acknowledged (with permission) in:

- Security advisories
- Release notes  
- This SECURITY.md file

---

Last updated: 2025-11-18
