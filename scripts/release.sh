#!/bin/bash
set -e

if [ -z "$1" ]; then
    echo "Usage: ./scripts/release.sh <version>"
    echo "Example: ./scripts/release.sh 0.3.3"
    exit 1
fi

VERSION=$1

if [ -z "$PYPI_TOKEN" ]; then
    echo "Error: PYPI_TOKEN not set. Source your ~/.zshrc or export it."
    exit 1
fi

echo "Releasing v$VERSION..."

sed -i '' "s/^version = \".*\"/version = \"$VERSION\"/" pyproject.toml

git add -A
git commit -m "v$VERSION release

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"

git push origin main

rm -rf dist/
uv run python -m build

uv run twine upload dist/* -u __token__ -p "$PYPI_TOKEN"

echo "Released v$VERSION to PyPI"
