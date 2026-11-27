#!/usr/bin/env bash
# Check out TCGdex's cards-database at the commit mappings/sources.json pins, then dump it to .cache/tcgdex/.
#
#     tools/sync_tcgdex.sh             the pinned commit
#     tools/sync_tcgdex.sh --latest    move the pin to the latest commit of master first
#
# TCGDEX_REPO names the checkout to use (default .cache/cards-database), so an existing clone can be reused.
# Needs git and bun. Only a refresh needs this: the committed data validates and builds without it.
set -euo pipefail
cd "$(dirname "$0")/.."

URL=https://github.com/tcgdex/cards-database.git
REPO=${TCGDEX_REPO:-.cache/cards-database}
PIN=mappings/sources.json

if [ ! -d "$REPO/.git" ]; then
    git clone --depth 1 "$URL" "$REPO"
fi
if [ "${1:-}" = "--latest" ]; then
    git -C "$REPO" fetch --depth 1 origin master
    python3 -c 'import json,sys; p=sys.argv[1]; d=json.load(open(p)); d["tcgdex"]["commit"]=sys.argv[2]; open(p,"w").write(json.dumps(d,indent=1)+"\n")' \
        "$PIN" "$(git -C "$REPO" rev-parse FETCH_HEAD)"
fi
COMMIT=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["tcgdex"]["commit"])' "$PIN")
if [ "$(git -C "$REPO" rev-parse HEAD)" != "$COMMIT" ]; then
    git -C "$REPO" fetch --depth 1 origin "$COMMIT"
    git -C "$REPO" -c advice.detachedHead=false checkout "$COMMIT"
fi
(cd "$REPO" && bun install --silent) && (cd "$REPO/server" && bun install --silent)
bun tools/dump_tcgdex.ts "$REPO" .cache/tcgdex
echo "$COMMIT" > .cache/tcgdex/commit.txt
