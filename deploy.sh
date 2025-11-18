#!/bin/bash
# SMTPBench Deployment Script
# Builds and publishes package to PyPI

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}SMTPBench Deployment Script${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Check if we're in the right directory
if [ ! -f "pyproject.toml" ]; then
    echo -e "${RED}Error: pyproject.toml not found. Run this script from the project root.${NC}"
    exit 1
fi

# Get current version from pyproject.toml
VERSION=$(grep "^version = " pyproject.toml | sed 's/version = "\(.*\)"/\1/')
echo -e "${BLUE}Current version: ${GREEN}${VERSION}${NC}"
echo ""

# Check if version is in __init__.py
INIT_VERSION=$(grep "__version__ = " smtpbench/__init__.py | sed 's/__version__ = "\(.*\)"/\1/')
if [ "$VERSION" != "$INIT_VERSION" ]; then
    echo -e "${RED}Error: Version mismatch!${NC}"
    echo -e "  pyproject.toml: ${VERSION}"
    echo -e "  __init__.py: ${INIT_VERSION}"
    exit 1
fi

# Check if we're on main branch
BRANCH=$(git branch --show-current)
if [ "$BRANCH" != "main" ]; then
    echo -e "${YELLOW}Warning: You are on branch '${BRANCH}', not 'main'${NC}"
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Check for uncommitted changes
if ! git diff-index --quiet HEAD --; then
    echo -e "${YELLOW}Warning: You have uncommitted changes${NC}"
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Ask for deployment target
echo -e "${BLUE}Select deployment target:${NC}"
echo "  1) TestPyPI (recommended for testing)"
echo "  2) PyPI (production)"
echo "  3) Both (TestPyPI first, then PyPI)"
read -p "Enter choice (1-3): " DEPLOY_TARGET

# Validate input
if [[ ! "$DEPLOY_TARGET" =~ ^[1-3]$ ]]; then
    echo -e "${RED}Invalid choice${NC}"
    exit 1
fi

echo ""
echo -e "${BLUE}Step 1: Cleaning old builds${NC}"
rm -rf dist/ build/ *.egg-info
echo -e "${GREEN}✓ Cleaned${NC}"
echo ""

echo -e "${BLUE}Step 2: Running tests${NC}"
if command -v pytest &> /dev/null; then
    pytest -v -m "not integration" --tb=short
    if [ $? -ne 0 ]; then
        echo -e "${RED}✗ Tests failed. Aborting deployment.${NC}"
        exit 1
    fi
    echo -e "${GREEN}✓ Tests passed${NC}"
else
    echo -e "${YELLOW}⚠ pytest not found, skipping tests${NC}"
fi
echo ""

echo -e "${BLUE}Step 3: Building package${NC}"
if [ -d ".venv" ]; then
    .venv/bin/python -m build
else
    python3 -m build
fi
echo -e "${GREEN}✓ Built${NC}"
echo ""

echo -e "${BLUE}Step 4: Checking package${NC}"
if [ -d ".venv" ]; then
    .venv/bin/twine check dist/*
else
    python3 -m twine check dist/*
fi
echo -e "${GREEN}✓ Package looks good${NC}"
echo ""

# Function to upload to a repository
upload_to_repo() {
    local repo=$1
    local repo_name=$2
    
    echo -e "${BLUE}Uploading to ${repo_name}...${NC}"
    
    if [ -d ".venv" ]; then
        if [ -z "$repo" ]; then
            .venv/bin/twine upload dist/*
        else
            .venv/bin/twine upload --repository $repo dist/*
        fi
    else
        if [ -z "$repo" ]; then
            python3 -m twine upload dist/*
        else
            python3 -m twine upload --repository $repo dist/*
        fi
    fi
    
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓ Successfully uploaded to ${repo_name}${NC}"
        return 0
    else
        echo -e "${RED}✗ Upload to ${repo_name} failed${NC}"
        return 1
    fi
}

# Deploy based on selection
case $DEPLOY_TARGET in
    1)
        echo -e "${BLUE}Step 5: Deploying to TestPyPI${NC}"
        upload_to_repo "testpypi" "TestPyPI"
        if [ $? -eq 0 ]; then
            echo ""
            echo -e "${GREEN}=====================================${NC}"
            echo -e "${GREEN}Deployment Complete!${NC}"
            echo -e "${GREEN}=====================================${NC}"
            echo ""
            echo -e "Test installation with:"
            echo -e "${YELLOW}pip install --index-url https://test.pypi.org/simple/ smtpbench==${VERSION}${NC}"
        fi
        ;;
    2)
        echo -e "${BLUE}Step 5: Deploying to PyPI${NC}"
        echo -e "${YELLOW}⚠ This will publish to production PyPI!${NC}"
        read -p "Are you sure? (yes/N) " -r
        echo
        if [[ $REPLY == "yes" ]]; then
            upload_to_repo "" "PyPI"
            if [ $? -eq 0 ]; then
                echo ""
                echo -e "${GREEN}=====================================${NC}"
                echo -e "${GREEN}Deployment Complete!${NC}"
                echo -e "${GREEN}=====================================${NC}"
                echo ""
                echo -e "Install with:"
                echo -e "${YELLOW}pip install smtpbench==${VERSION}${NC}"
                echo ""
                echo -e "Don't forget to:"
                echo "  1. Create a GitHub release/tag: git tag v${VERSION} && git push origin v${VERSION}"
                echo "  2. Update the GitHub release notes"
            fi
        else
            echo -e "${YELLOW}Deployment cancelled${NC}"
            exit 1
        fi
        ;;
    3)
        echo -e "${BLUE}Step 5a: Deploying to TestPyPI${NC}"
        upload_to_repo "testpypi" "TestPyPI"
        if [ $? -ne 0 ]; then
            exit 1
        fi
        
        echo ""
        echo -e "${YELLOW}TestPyPI upload successful. Test before proceeding to PyPI.${NC}"
        echo -e "Test installation with:"
        echo -e "${YELLOW}pip install --index-url https://test.pypi.org/simple/ smtpbench==${VERSION}${NC}"
        echo ""
        read -p "Continue to PyPI? (yes/N) " -r
        echo
        
        if [[ $REPLY == "yes" ]]; then
            echo -e "${BLUE}Step 5b: Deploying to PyPI${NC}"
            upload_to_repo "" "PyPI"
            if [ $? -eq 0 ]; then
                echo ""
                echo -e "${GREEN}=====================================${NC}"
                echo -e "${GREEN}Deployment Complete!${NC}"
                echo -e "${GREEN}=====================================${NC}"
                echo ""
                echo -e "Install with:"
                echo -e "${YELLOW}pip install smtpbench==${VERSION}${NC}"
                echo ""
                echo -e "Don't forget to:"
                echo "  1. Create a GitHub release/tag: git tag v${VERSION} && git push origin v${VERSION}"
                echo "  2. Update the GitHub release notes"
            fi
        else
            echo -e "${YELLOW}PyPI deployment cancelled${NC}"
        fi
        ;;
esac

echo ""
echo -e "${BLUE}Done!${NC}"
