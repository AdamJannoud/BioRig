#!/usr/bin/env bash
# Submits the canonical ERC-6551 registry to Blockscout for verification and records the explorer's
# own answer. Blockscout limits the unauthenticated v1 API to 10 requests per IP per window, and this
# IP's window is spent, so the script first waits for the window to reopen (a 429 costs no quota, so
# polling the reset header is free), then submits once.
#
# Usage: script/submit-registry-when-open.sh              # CHAIN_ID from the environment, else the repo default
#        CHAIN_ID=42220 script/submit-registry-when-open.sh
set -uo pipefail
cd "$(dirname "$0")/.."

CHAIN_ID=$(python3 -m dashboard.config get chain_id) || exit 2
B=$(python3 -m dashboard.config get explorer_url --chain-id "$CHAIN_ID") || exit 2
REG=0x000000006551c19487814612e58FE06813775758
LOG=evidence/registry-submit.log
PROJ=/tmp/regverify

exec > >(tee -a "$LOG") 2>&1
echo "=== started $(date -u +%FT%TZ) on chain $CHAIN_ID ($B) ==="

remaining() {
  curl -s -D - -o /dev/null "$B/api?module=block&action=eth_block_number" \
    | awk 'tolower($1)=="x-ratelimit-remaining:"{gsub(/\r/,"");print $2}'
}

# --- 1. wait for the quota window to reopen (max ~22 minutes) -------------------
for i in $(seq 1 45); do
  r=$(remaining)
  echo "$(date -u +%FT%TZ) v1 requests left this window: ${r:-unknown}"
  [ "${r:-0}" != "0" ] && break
  sleep 30
done
echo "--- window state before submitting: $(curl -s -o /dev/null -w '%{http_code}' "$B/api?module=block&action=eth_block_number") ---"

# --- 2. state before ------------------------------------------------------------
before=$(curl -s "$B/api/v2/smart-contracts/$REG" | jq -c '{is_verified,is_partially_verified,is_fully_verified,is_verified_via_eth_bytecode_db,verified_at,name}')
echo "before: $before"

# --- 3. build a project with the canonical source at the canonical settings -----
# The canonical source text is fetched fresh (blockscout's record of the same contract on mainnet)
# so this does not depend on anything left in /tmp.
rm -rf "$PROJ"; mkdir -p "$PROJ/src"
curl -s "https://eth.blockscout.com/api/v2/smart-contracts/$REG" | jq -r '.source_code' > "$PROJ/src/ERC6551Registry.sol"
wc -c "$PROJ/src/ERC6551Registry.sol"
cat > "$PROJ/foundry.toml" <<'TOML'
[profile.default]
src = "src"
out = "out"
solc = "0.8.17"
evm_version = "london"
optimizer = true
optimizer_runs = 200
TOML

if ! (cd "$PROJ" && forge build); then
  echo "!!! local build failed, aborting before any submission"
  exit 1
fi

# --- 4. submit, and capture Blockscout's own words ------------------------------
echo "=== submitting $(date -u +%FT%TZ) ==="
(cd "$PROJ" && forge verify-contract "$REG" src/ERC6551Registry.sol:ERC6551Registry \
  --verifier blockscout --verifier-url "$B/api?" --chain "$CHAIN_ID" \
  --skip-is-verified-check); submit_rc=$?
echo "=== forge verify-contract exit $submit_rc $(date -u +%FT%TZ) ==="

# --- 5. what the explorer says afterwards ---------------------------------------
sleep 20
after=$(curl -s "$B/api/v2/smart-contracts/$REG" | jq -c '{is_verified,is_partially_verified,is_fully_verified,is_verified_via_eth_bytecode_db,verified_at,name}')
echo "after:  $after"
echo "before: $before"
