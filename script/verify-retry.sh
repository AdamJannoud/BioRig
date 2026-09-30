#!/usr/bin/env bash
# Verifies the two contracts Blockscout still needs, within its unauthenticated quota.
#
# Blockscout's v1 API (module=contract) allows 10 requests per window for an unauthenticated IP.
# The window length is in the x-ratelimit-reset header, in milliseconds. forge verify-contract
# spends 1 request on the submission and then retries itself 3 times on a 429, so ONE attempt can
# cost 4 requests: two attempts exhaust a window. Earlier versions of this script looped inside a
# single window and that is exactly what drained the quota, so there is no loop here. Status is
# read through the v2 API, which is not quota-limited.
#
# Usage:  ./script/verify-retry.sh status           # free, v2 only
#         ./script/verify-retry.sh proxy            # one attempt
#         ./script/verify-retry.sh registry         # one attempt
set -uo pipefail
cd /workspace/bio-rig
set -a; . ./.env; set +a

PROXY=0x21ab8B36177F65ce69e04E281E4aFf3Db6b5f7E6
REG=0x000000006551c19487814612e58FE06813775758
IMPL=0x4c998C6553C78bb9d5A67Aac6fBC526d64DBa3a4
ACCT=0x3d8a53dB1bBcab6D47097B25080527e5560C5165
HOST=https://celo-sepolia.blockscout.com
VU=$HOST/api
V2=$HOST/api/v2/addresses
mkdir -p evidence
LOG=evidence/verify-retry.log

is_verified() { curl -s "$V2/$1" | jq -r '.is_verified // false'; }

report() {
  echo "=== verification status $(date -u +%FT%TZ) ==="
  for a in "$REG" "$PROXY" "$IMPL" "$ACCT"; do
    printf '%s  is_verified=%s\n' "$a" "$(is_verified "$a")"
  done
}

# Reads the current window without spending a request that counts: a 429 response is rejected
# before it is charged, and while remaining is 0 this is free. When quota is available this costs
# one request, so it is only called after a failed attempt.
print_window() {
  local h
  h=$(curl -s -D - -o /dev/null "$VU?module=contract&action=getsourcecode&address=$PROXY" \
      | grep -iE 'x-ratelimit-(limit|remaining|reset)' | tr -d '\r')
  local left reset
  left=$(echo "$h" | awk -F': ' '/remaining/{print $2}')
  reset=$(echo "$h" | awk -F': ' '/reset/{print $2}')
  if [ -n "${reset:-}" ] && [ "${reset:-0}" -gt 0 ] 2>/dev/null; then
    printf 'quota: remaining=%s  window resets in %ss at %sZ\n' \
      "${left:-?}" "$((reset / 1000))" "$(date -u -d "+$((reset / 1000)) seconds" +%FT%T)"
  fi
}

one_attempt() {
  local addr=$1 fqn=$2 label=$3; shift 3
  echo "--- $label: single attempt $(date -u +%FT%TZ) ---"
  forge verify-contract "$addr" "$fqn" --verifier blockscout --verifier-url "$VU" \
    --chain 11142220 --skip-is-verified-check "$@" 2>&1 \
    | grep -v '^Constructor args' | tail -10
  sleep 10
  local v; v=$(is_verified "$addr")
  echo "blockscout is_verified=$v"
  if [ "$v" = "true" ]; then echo "RESULT $label: VERIFIED"; else print_window; fi
}

INIT=$(cast calldata "initialize(address,address,address,uint256,address,address)" \
  0xb5aB2054b43040593805Cf662A938eFE924F2778 \
  0x000000006551c19487814612e58FE06813775758 \
  "$ACCT" \
  11142220 \
  0xb5aB2054b43040593805Cf662A938eFE924F2778 \
  0x0000000000000000000000000000000000000000)
ARGS=$(cast abi-encode "f(address,bytes)" "$IMPL" "$INIT")

case "${1:-status}" in
  status)   report ;;
  proxy)    one_attempt "$PROXY" \
              "lib/openzeppelin-contracts/contracts/proxy/ERC1967/ERC1967Proxy.sol:ERC1967Proxy" \
              proxy --constructor-args "$ARGS"
            report ;;
  # The canonical registry cannot be exact-match verified from what is available here. Compiling it
  # with solc 0.8.17, optimizer on, runs 200, evm london reproduces the on-chain executable code
  # exactly (see script/registry-byte-match.py), but the 53-byte metadata blob differs in its 32-byte
  # content hash, which is keccak256 over the metadata JSON covering the original source text and its
  # path. Neither this repo's vendored copy nor Blockscout's stored mainnet copy reproduces that hash,
  # so this branch submits with the matching compiler settings and records whatever Blockscout says.
  registry) one_attempt "$REG" src/vendor/ERC6551Registry.sol:ERC6551Registry canonical-registry \
              --compiler-version v0.8.17 --num-of-optimizations 200 --evm-version london
            report ;;
  *)        echo "usage: $0 [status|proxy|registry]" >&2; exit 2 ;;
esac
