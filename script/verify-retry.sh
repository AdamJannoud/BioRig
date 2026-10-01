#!/usr/bin/env bash
# Verifies BioRig's contracts on Blockscout, for whichever chain CHAIN_ID selects (from the environment or .env,
# else the repo default). Every address comes from that chain's DeployAll broadcast and the explorer from
# dashboard/chains.json, so the same script serves Celo Sepolia and Celo mainnet.
#
# On Celo Sepolia all four are verified (2026-09-30): the canonical registry as a partial match via Blockscout's
# Ethereum Bytecode Database, the other three from own submissions. The 'registry' target below is kept for
# redeployments and for the record; the manual submission note is in DEPLOY.md section 7.
# Prefer the v2 verify route (POST /api/v2/smart-contracts/{addr}/verification/via/flattened-code):
# the v1 module=contract API throttles to 10 requests per window, the v2 route ran at 180 here.
#
# Blockscout's v1 API (module=contract) allows 10 requests per window for an unauthenticated IP.
# The window length is in the x-ratelimit-reset header, in milliseconds. forge verify-contract
# spends 1 request on the submission and then retries itself 3 times on a 429, so ONE attempt can
# cost 4 requests: two attempts exhaust a window. Earlier versions of this script looped inside a
# single window and that is exactly what drained the quota, so there is no loop here. Status is
# read through the v2 API, which is not quota-limited.
#
# Usage:  ./script/verify-retry.sh status           # free, v2 only
#         ./script/verify-retry.sh proxy            # one attempt each:
#         ./script/verify-retry.sh core             #   BioRigCoreV5 implementation
#         ./script/verify-retry.sh account          #   ERC-6551 account implementation
#         ./script/verify-retry.sh registry         #   canonical registry
#         CHAIN_ID=42220 ./script/verify-retry.sh status
set -uo pipefail
cd "$(dirname "$0")/.."

CHAIN_ID=$(python3 -m dashboard.config get chain_id) || exit 2
HOST=$(python3 -m dashboard.config get explorer_url --chain-id "$CHAIN_ID") || exit 2
REG=$(python3 -m dashboard.config get erc6551_registry --chain-id "$CHAIN_ID") || exit 2
RUN=broadcast/DeployAll.s.sol/$CHAIN_ID/run-latest.json
[ -f "$RUN" ] || { echo "no DeployAll broadcast for chain $CHAIN_ID ($RUN); nothing to verify" >&2; exit 2; }
created() { jq -r --arg n "$1" '[.transactions[] | select(.transactionType == "CREATE" and .contractName == $n)]
                                 | last | .contractAddress // empty' "$RUN"; }
PROXY=$(created ERC1967Proxy)
IMPL=$(created BioRigCoreV5)
ACCT=$(created ERC6551Account)
VU=$HOST/api
V2=$HOST/api/v2/addresses
echo "chain $CHAIN_ID ($HOST): proxy $PROXY, core $IMPL, account $ACCT, registry $REG"

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
    --chain "$CHAIN_ID" --skip-is-verified-check "$@" 2>&1 \
    | grep -v '^Constructor args' | tail -10
  sleep 10
  local v; v=$(is_verified "$addr")
  echo "blockscout is_verified=$v"
  if [ "$v" = "true" ]; then echo "RESULT $label: VERIFIED"; else print_window; fi
}

# The proxy's constructor args exactly as broadcast: (implementation, initialize calldata).
ARGS=$(cast abi-encode "f(address,bytes)" $(jq -r '[.transactions[] | select(.transactionType == "CREATE"
    and .contractName == "ERC1967Proxy")] | last | .arguments | join(" ")' "$RUN"))

case "${1:-status}" in
  status)   report ;;
  proxy)    one_attempt "$PROXY" \
              "lib/openzeppelin-contracts/contracts/proxy/ERC1967/ERC1967Proxy.sol:ERC1967Proxy" \
              proxy --constructor-args "$ARGS"
            report ;;
  core)     one_attempt "$IMPL" src/BioRigCoreV5.sol:BioRigCoreV5 core; report ;;
  account)  one_attempt "$ACCT" src/vendor/ERC6551Account.sol:ERC6551Account account; report ;;
  # The canonical registry cannot be exact-match verified from what is available here. Compiling it
  # with solc 0.8.17, optimizer on, runs 200, evm london reproduces the on-chain executable code
  # exactly (see script/registry-byte-match.py), but the 53-byte metadata blob differs in its 32-byte
  # content hash, which is keccak256 over the metadata JSON covering the original source text and its
  # path. Neither this repo's vendored copy nor Blockscout's stored mainnet copy reproduces that hash,
  # so this branch submits with the matching compiler settings and records whatever Blockscout says.
  registry) one_attempt "$REG" src/vendor/ERC6551Registry.sol:ERC6551Registry canonical-registry \
              --compiler-version v0.8.17 --num-of-optimizations 200 --evm-version london
            report ;;
  *)        echo "usage: $0 [status|proxy|core|account|registry]" >&2; exit 2 ;;
esac
