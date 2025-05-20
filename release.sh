#!/bin/sh

git status | grep -q "nothing to commit"
dirty=($? != 0)
if (( dirty )); then
    git stash -u
fi

uv build --wheel

git push origin
git push origin v$1
gh release create v$1 --verify-tag --title "Release $1" --notes ""
gh release upload v$1 dist/mapmaker-$1-py3-none-any.whl

if (( dirty )); then
    git stash pop --quiet
fi
