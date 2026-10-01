#!/usr/bin/env bash
# Rehearse the PENDING Celo mainnet role handover against a fork of the LIVE chain, using the live proxy and the real
# deployer key as the local sender. Nothing is broadcast: anvil is forked, the handover runs on the fork, anvil stops.
# Only the fork's own stand-ins (VERIFIER_ADDRESS, NEW_ADMIN Safe) are anvil accounts.
set -uo pipefail
cd "$(dirname "$0")/.."
export HOME=/root
CHAIN_ID=42220
FORK_URL=$(python3 -m dashboard.config get rpc_url --chain-id 42220)
PROXY=0x04Db169dDF8AbB80943161C01B2a71DC40384E64
PORT=${FORK_PORT:-8549}
LOCAL="http://127.0.0.1:$PORT"
KEY=${KEY_FILE:-/tmp/biorig-audit/deployer.key}

anvil --fork-url "$FORK_URL" --port "$PORT" --silent &
ANVIL_PID=$!
trap 'kill $ANVIL_PID 2>/dev/null; wait $ANVIL_PID 2>/dev/null; echo "[anvil stopped]"' EXIT
for _ in $(seq 1 120); do cast chain-id --rpc-url "$LOCAL" >/dev/null 2>&1 && break; sleep 0.5; done

export FOUNDRY_BROADCAST=cache/handover-fork-check/broadcast
export PRIVATE_KEY=$(cat "$KEY")
export CHAIN_ID PROXY_ADDRESS="$PROXY"
DEPLOYER=$(cast wallet address --private-key "$PRIVATE_KEY")
ADMIN_ROLE=0x0000000000000000000000000000000000000000000000000000000000000000
UPGRADER_ROLE=$(cast keccak UPGRADER_ROLE)
VERIFIER_ROLE=$(cast keccak VERIFIER_ROLE)
role() { cast call "$PROXY" "hasRole(bytes32,address)(bool)" "$1" "$2" --rpc-url "$LOCAL"; }
who() { # who <label> <address>
    echo "  ${1}  admin=$(role $ADMIN_ROLE "$2") upgrader=$(role "$UPGRADER_ROLE" "$2") verifier=$(role "$VERIFIER_ROLE" "$2")"
}

echo "### fork facts"
echo "fork chain id: $(cast chain-id --rpc-url "$LOCAL")   fork block: $(cast block-number --rpc-url "$LOCAL")"
echo "live proxy $PROXY  code size $(cast codesize "$PROXY" --rpc-url "$LOCAL")"
echo "sender (real deployer key, local only) $DEPLOYER  balance $(cast balance "$DEPLOYER" --rpc-url "$LOCAL")"
echo "### BEFORE, against live mainnet state"
who deployer "$DEPLOYER"

MNEMONIC="test test test test test test test test test test test junk"
VERIFIER_KEY=$(cast wallet private-key --mnemonic "$MNEMONIC" --mnemonic-index 2)
export VERIFIER_ADDRESS=$(cast wallet address --private-key "$VERIFIER_KEY")
SAFE_OWNER_KEY=$(cast wallet private-key --mnemonic "$MNEMONIC" --mnemonic-index 3)
SAFE_OWNER=$(cast wallet address --private-key "$SAFE_OWNER_KEY")
ZERO=0x0000000000000000000000000000000000000000
SAFE_FACTORY=0x4e1DCf7AD4e460CfD30791CCC4F9c8a4f820ec67
SAFE_L2_SINGLETON=0x29fcB43b46531BcA003ddC8FCB67FFE91900C762
SAFE_FALLBACK_HANDLER=0xfd0732Dc9E303f09fCEf3a7388Ad10A83459Ec99
export NEW_ADMIN_OWNER=$SAFE_OWNER

echo "### fork stand-ins: NEW_ADMIN Safe (owner $SAFE_OWNER), VERIFIER_ADDRESS $VERIFIER_ADDRESS"
cast rpc anvil_setBalance "$SAFE_OWNER" 0xde0b6b3a7640000 --rpc-url "$LOCAL" >/dev/null
SETUP=$(cast calldata "setup(address[],uint256,address,bytes,address,address,uint256,address)" \
    "[$SAFE_OWNER]" 1 $ZERO 0x $SAFE_FALLBACK_HANDLER $ZERO 0 $ZERO)
SALT_NONCE=$(date +%s)
SAFE=$(cast call $SAFE_FACTORY "createProxyWithNonce(address,bytes,uint256)(address)" $SAFE_L2_SINGLETON "$SETUP" "$SALT_NONCE" --from "$SAFE_OWNER" --rpc-url "$LOCAL")
cast send $SAFE_FACTORY "createProxyWithNonce(address,bytes,uint256)" $SAFE_L2_SINGLETON "$SETUP" "$SALT_NONCE" \
    --private-key "$SAFE_OWNER_KEY" --rpc-url "$LOCAL" | grep -E "^status"
export NEW_ADMIN=$SAFE
echo "Safe $SAFE threshold $(cast call "$SAFE" "getThreshold()(uint256)" --rpc-url "$LOCAL") owners $(cast call "$SAFE" "getOwners()(address[])" --rpc-url "$LOCAL")"

echo
echo "### handover dry run (no --broadcast)"
forge script --rpc-url "$LOCAL" script/HardenMainnetAdmin.s.sol:HardenMainnetAdmin
echo "dry-run exit=$?"

echo
echo "### handover broadcast to the fork"
OUT=$(forge script --rpc-url "$LOCAL" script/HardenMainnetAdmin.s.sol:HardenMainnetAdmin --broadcast 2>&1); RC=$?
echo "$OUT" | sed -n '/== Logs ==/,$p'
echo "broadcast exit=$RC"

echo
echo "### AFTER, read back from the fork"
who deployer "$DEPLOYER"
who Safe "$SAFE"
who verifier "$VERIFIER_ADDRESS"

echo
echo "### post-handover behaviour on the fork"
PLANTER=0x$(cast keccak "biorig-handover-check-planter" | cut -c27-66)
cast send "$PROXY" "mintTree(address,bytes32,uint96,uint96)" "$PLANTER" "$(cast keccak plot-fork-1)" 10 20 \
    --private-key "$PRIVATE_KEY" --rpc-url "$LOCAL" >/dev/null 2>&1
echo "deployer mint  exit=$? (expect non-zero: renounced)"
cast send "$PROXY" "pause()" --private-key "$PRIVATE_KEY" --rpc-url "$LOCAL" >/dev/null 2>&1
echo "deployer pause exit=$? (expect non-zero: renounced)"
cast send "$PROXY" "mintTree(address,bytes32,uint96,uint96)" "$PLANTER" "$(cast keccak plot-fork-1)" 10 20 \
    --private-key "$VERIFIER_KEY" --rpc-url "$LOCAL" | grep -E "^status"
echo "verifier mint  exit=$? (expect 0)"
TBA=$(cast call "$PROXY" "getTreeStats(uint256)((uint96,uint96,uint64,address,bool,bytes32))" 1 --rpc-url "$LOCAL" | tr -d '() ' | cut -d, -f4)
echo "TBA $TBA token() = $(cast call "$TBA" "token()(uint256,address,uint256)" --rpc-url "$LOCAL" | tr '\n' ' ')"
echo "second handover run:"; forge script --rpc-url "$LOCAL" script/HardenMainnetAdmin.s.sol:HardenMainnetAdmin 2>&1 | tail -3
