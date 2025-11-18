# Deployment Guide

This guide explains how to deploy SMTPBench to PyPI.

## Prerequisites

1. **PyPI Account**: Create accounts on both [PyPI](https://pypi.org) and [TestPyPI](https://test.pypi.org)
2. **API Tokens**: Generate API tokens for both services
3. **Build Tools**: Ensure you have `build` and `twine` installed (handled by the script)

## Quick Start

The easiest way to deploy is using the deployment script:

```bash
./deploy.sh
```

The script will guide you through:
1. Version verification
2. Git branch and status checks
3. Running tests
4. Building the package
5. Uploading to PyPI and/or TestPyPI

## Deployment Options

When you run `./deploy.sh`, you'll be prompted to choose:

1. **TestPyPI** - Test the deployment without affecting production
2. **PyPI** - Deploy to production
3. **Both** - Deploy to TestPyPI first, then PyPI (recommended)

## Setup PyPI Tokens

### Option 1: Environment Variables (Recommended)

```bash
export TWINE_USERNAME=__token__
export TWINE_PASSWORD=pypi-YOUR_TOKEN_HERE
```

### Option 2: Configuration File

Copy the example config:

```bash
cp .pypirc.example ~/.pypirc
chmod 600 ~/.pypirc
```

Edit `~/.pypirc` and add your tokens:

```ini
[pypi]
username = __token__
password = pypi-YOUR_PRODUCTION_TOKEN_HERE

[testpypi]
username = __token__
password = pypi-YOUR_TEST_TOKEN_HERE
```

## Manual Deployment

If you prefer to deploy manually:

### 1. Update Version

Update version in both files:
- `pyproject.toml`
- `smtpbench/__init__.py`

### 2. Clean and Build

```bash
# Clean old builds
rm -rf dist/ build/ *.egg-info

# Build package
python3 -m build
```

### 3. Check Package

```bash
twine check dist/*
```

### 4. Upload to TestPyPI (Optional)

```bash
twine upload --repository testpypi dist/*
```

Test installation:
```bash
pip install --index-url https://test.pypi.org/simple/ smtpbench
```

### 5. Upload to PyPI

```bash
twine upload dist/*
```

## Post-Deployment

After successful deployment:

### 1. Create Git Tag

```bash
git tag v1.1.0
git push origin v1.1.0
```

### 2. Create GitHub Release

Go to https://github.com/SMTPBench/SMTPBench/releases/new

- Tag: `v1.1.0`
- Title: `SMTPBench v1.1.0`
- Description: Copy from CHANGELOG.md

### 3. Verify Installation

```bash
pip install --upgrade smtpbench
smtpbench --version
```

## Version Bumping

Before each release, update the version number:

1. **Patch release** (bug fixes): `1.1.0` → `1.1.1`
2. **Minor release** (new features): `1.1.0` → `1.2.0`
3. **Major release** (breaking changes): `1.1.0` → `2.0.0`

Update in:
- `pyproject.toml` (line 7)
- `smtpbench/__init__.py` (line 3)
- `CHANGELOG.md` (add new version section)

## Troubleshooting

### "Version already exists"

You cannot re-upload the same version. You must bump the version number.

### "Invalid credentials"

Check your API token is correct and has upload permissions.

### "Package not found on TestPyPI"

Some dependencies might not be available on TestPyPI. This is expected and won't affect the real PyPI upload.

### Build warnings about license format

The warnings about license classifiers are harmless. The package will work fine. You can update the format later if desired.

## CI/CD Integration

For automated deployments, see `.github/workflows/` for GitHub Actions examples.

You can trigger automated PyPI uploads on:
- Git tags matching `v*.*.*`
- Manual workflow dispatch
- After successful CI tests

## Security Notes

- **Never commit** `.pypirc` or tokens to git
- Use **separate tokens** for TestPyPI and PyPI
- Consider using **GitHub Secrets** for CI/CD deployments
- Set token **scope to upload only**, not full account access
- **Rotate tokens** regularly

## Support

For deployment issues:
- Check [PyPI Status](https://status.python.org/)
- Review [Twine Documentation](https://twine.readthedocs.io/)
- Open an issue on GitHub

---

Last updated: 2025-11-18
