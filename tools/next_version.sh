#!/usr/bin/env bash
# The tag of the next patch release: the highest v<major>.<minor>.<patch> tag, its patch plus one.
#
#     tools/next_version.sh        ->  v0.3.1 after v0.3.0
set -euo pipefail
latest=$(git tag -l 'v[0-9]*.[0-9]*.[0-9]*' --sort=-v:refname | head -n 1)
if [ -z "$latest" ]; then
    echo "no release tag to follow" >&2
    exit 1
fi
IFS=. read -r major minor patch <<< "${latest#v}"
echo "v$major.$minor.$((patch + 1))"
