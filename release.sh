#!/bin/sh

git stash
poetry build -f wheel
gh release create v$1 --verify-tag --title "Release $1" --notes ""
gh release upload v$1 dist/mapmaker-$1-py3-none-any.whl
git stash pop --quiet
