#!/usr/bin/env bash
# Fork dry run of the deployment and the role handover against real chain state. Starts anvil forked from the
# chosen chain, runs the scripts against it, and stops anvil on exit, so nothing is left running. Nothing is sent
# to the real chain.
#
# Every PRIVATE_KEY below is one of anvil's well-known accounts (derived from anvil's public test mnemonic). They are
# PUBLIC. Use them only against this local fork and never for a real broadcast.
#
# Usage: script/fork-dry-run.sh [FORK_URL]
#   CHAIN_ID=42220 script/fork-dry-run.sh        # Celo mainnet, RPC from dashboard/chains.json
#   script/fork-dry-run.sh https://forno.celo.org # chain id read from the RPC
# With neither, the repo's default chain (dashboard/deployment.json) and its RPC from dashboard/chains.json. Given
# both, they must agree. The chain must be in dashboard/chains.json.
#   FORK_WIPE_REGISTRY=1  clears the canonical registry's code on the fork first, to rehearse a chain without it
#                         (neither Celo network is one any more, so step 1's refusing branch needs this to run)
#   FORK_PORT=8547        anvil's local port
set -uo pipefail
cd "$(dirname "$0")/.."

cfg() { python3 -m dashboard.config get "$@"; } # the chain registry, read by dashboard/config.py

FORK_URL="${1:-${FORK_URL:-}}"
if [ -n "$FORK_URL" ]; then
    UPSTREAM_ID=$(cast chain-id --rpc-url "$FORK_URL") || { echo "cannot read eth_chainId from $FORK_URL" >&2; exit 2; }
    if [ -n "${CHAIN_ID:-}" ] && [ "$CHAIN_ID" != "$UPSTREAM_ID" ]; then
        echo "CHAIN_ID=$CHAIN_ID but $FORK_URL reports chain $UPSTREAM_ID; refusing to rehearse the wrong chain" >&2
        exit 2
    fi
    CHAIN_ID=$UPSTREAM_ID
else
    CHAIN_ID=$(cfg chain_id ${CHAIN_ID:+--chain-id "$CHAIN_ID"}) || exit 2
    FORK_URL=$(cfg rpc_url --chain-id "$CHAIN_ID") || exit 2
fi
CHAIN_NAME=$(cfg name --chain-id "$CHAIN_ID") || exit 2
REGISTRY_CODEHASH=$(cfg erc6551_registry_codehash --chain-id "$CHAIN_ID")
PORT=${FORK_PORT:-8547}
LOCAL="http://127.0.0.1:$PORT"

anvil --fork-url "$FORK_URL" --port "$PORT" --silent &
ANVIL_PID=$!
trap 'kill $ANVIL_PID 2>/dev/null; wait $ANVIL_PID 2>/dev/null; echo "[anvil stopped]"' EXIT
for _ in $(seq 1 60); do cast chain-id --rpc-url "$LOCAL" >/dev/null 2>&1 && break; sleep 0.5; done

# The fork reports the upstream chain id, so without this forge would file the fork's broadcast logs under
# broadcast/<script>/<chain id>/, where they would look like a real deployment.
export FOUNDRY_BROADCAST=cache/fork-dry-run/broadcast
MNEMONIC="test test test test test test test test test test test junk" # anvil's public dev mnemonic
anvil_key() { cast wallet private-key --mnemonic "$MNEMONIC" --mnemonic-index "$1"; }
export PRIVATE_KEY=0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80 # anvil #0, local fork only
export ADMIN=0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266                                # anvil #0
export BUFFER_POOL=0x70997970C51812dc3A010C7d01b50e0d17dc79C8                          # anvil #1
export URI_GENERATOR=0x0000000000000000000000000000000000000000
export CHAIN_ID
export RPC_URL="$LOCAL" # what scripts/record_deployment.py checks the proxy's code against
export ERC6551_REGISTRY=$(cfg erc6551_registry --chain-id "$CHAIN_ID")
export ERC6551_IMPLEMENTATION=0x4e59b44847b379578588920cA78FbF26c0B4956C # placeholder with code; replaced in step 4
[ "$(cast wallet address --private-key "$PRIVATE_KEY")" = "$ADMIN" ] || { echo "anvil #0 key mismatch" >&2; exit 2; }
VERIFIER_KEY=$(anvil_key 2)       # stands in for the dedicated server-side verifier key
VERIFIER_ADDRESS=$(cast wallet address --private-key "$VERIFIER_KEY")
SAFE_OWNER_KEY=$(anvil_key 3)     # stands in for the Safe's signer; not the deployer
SAFE_OWNER=$(cast wallet address --private-key "$SAFE_OWNER_KEY")
# Safe v1.4.1 canonical deployments (safe-global/safe-deployments), present on both Celo networks.
SAFE_FACTORY=0x4e1DCf7AD4e460CfD30791CCC4F9c8a4f820ec67
SAFE_L2_SINGLETON=0x29fcB43b46531BcA003ddC8FCB67FFE91900C762
SAFE_FALLBACK_HANDLER=0xfd0732Dc9E303f09fCEf3a7388Ad10A83459Ec99
ZERO=0x0000000000000000000000000000000000000000

step() { printf '\n\n######## %s\n' "$*"; }
FAILED=0
check() { # check <rc> <ok|fail> <label>: records whether an exit status matched what the step requires
    local rc=$1 want=$2; shift 2
    if { [ "$want" = ok ] && [ "$rc" -eq 0 ]; } || { [ "$want" = fail ] && [ "$rc" -ne 0 ]; }; then
        echo ">>> AS EXPECTED ($want, exit $rc): $*"
    else
        echo ">>> UNEXPECTED (wanted $want, exit $rc): $*"; FAILED=1
    fi
}
expect() { check $? "$@"; } # expect <ok|fail> <label>: the previous command's exit status
has() { # has <haystack> <needle> <label>: the step must have said this, so a pass for the wrong reason is caught
    if grep -qF -- "$2" <<<"$1"; then echo ">>> AS EXPECTED (output has '$2'): $3"
    else echo ">>> UNEXPECTED (output lacks '$2'): $3"; FAILED=1; fi
}
lacks() {
    if grep -qF -- "$2" <<<"$1"; then echo ">>> UNEXPECTED (output has '$2'): $3"; FAILED=1
    else echo ">>> AS EXPECTED (output lacks '$2'): $3"; fi
}
same() { # same <got> <want> <label>, case-insensitive (addresses)
    if [ "${1,,}" = "${2,,}" ]; then echo ">>> AS EXPECTED ($1): $3"
    else echo ">>> UNEXPECTED (got '$1', wanted '$2'): $3"; FAILED=1; fi
}
FS="forge script --rpc-url $LOCAL"
REGISTRY_GUARD="ERC6551_REGISTRY has no code on this chain"

step "0. Fork facts"
echo "chain:    $CHAIN_NAME ($CHAIN_ID), upstream $FORK_URL"
echo "fork eth_chainId: $(cast chain-id --rpc-url "$LOCAL")   fork block: $(cast block-number --rpc-url "$LOCAL")"
if [ "${FORK_WIPE_REGISTRY:-}" = 1 ]; then
    cast rpc anvil_setCode "$ERC6551_REGISTRY" 0x --rpc-url "$LOCAL" >/dev/null
    cast rpc anvil_setNonce "$ERC6551_REGISTRY" 0x0 --rpc-url "$LOCAL" >/dev/null # else CREATE2 collides on nonce 1
    echo "FORK_WIPE_REGISTRY=1: registry code cleared on the fork (the real chain is untouched)"
fi
REGISTRY_CODE=$(cast code "$ERC6551_REGISTRY" --rpc-url "$LOCAL")
echo "code size at canonical ERC-6551 registry $ERC6551_REGISTRY: $(cast codesize "$ERC6551_REGISTRY" --rpc-url "$LOCAL")"
echo "code size at Nick's factory 0x4e59b448...: $(cast codesize 0x4e59b44847b379578588920cA78FbF26c0B4956C --rpc-url "$LOCAL")"
echo "verifier stand-in $VERIFIER_ADDRESS (anvil #2), Safe owner stand-in $SAFE_OWNER (anvil #3)"

# The registry guard's expected outcome depends on the chain: where the canonical registry is absent it must refuse,
# where it is present (Celo mainnet always, Celo Sepolia since 30 September 2026) it must pass, and the code there
# must be the canonical registry's, not merely something at that address.
if [ "$REGISTRY_CODE" = "0x" ]; then
    step "1. GUARD: DeployBioRig with the canonical registry, which has no code on this fork (must refuse)"
    OUT=$($FS script/DeployBioRig.s.sol:DeployBioRig 2>&1); RC=$?; echo "$OUT"
    check $RC fail "registry-code guard fired"
    has "$OUT" "$REGISTRY_GUARD" "it was the registry guard that refused, not something else"
else
    step "1. REGISTRY PRESENT: the canonical registry has code on this fork, so the registry-code guard must pass"
    same "$(cast keccak "$REGISTRY_CODE")" "$REGISTRY_CODEHASH" "registry runtime code is the canonical one (chains.json codehash)"
    OUT=$($FS script/DeployBioRig.s.sol:DeployBioRig 2>&1); RC=$?; echo "$OUT"
    check $RC ok "DeployBioRig accepted the existing registry"
    lacks "$OUT" "$REGISTRY_GUARD" "registry guard did not fire"
fi

step "2. GUARD: DeployBioRig with CHAIN_ID=44787 (Alfajores) against a $CHAIN_NAME RPC (must refuse)"
OUT=$(CHAIN_ID=44787 $FS script/DeployBioRig.s.sol:DeployBioRig 2>&1); RC=$?; echo "$OUT"
check $RC fail "chain-id guard fired"
has "$OUT" "CHAIN_ID mismatch" "it was the chain-id guard that refused"

step "3. DRY RUN (no --broadcast): DeployERC6551Registry, canonical mode"
OUT=$($FS script/DeployERC6551Registry.s.sol:DeployERC6551Registry 2>&1); RC=$?; echo "$OUT"
check $RC ok "registry deployment simulated"
[ "$REGISTRY_CODE" != "0x" ] && has "$OUT" "already deployed on this chain; reusing it" "existing registry reused, not redeployed"

step "4. LOCAL FORK SETUP ONLY: broadcast the registry and example account to the anvil fork (not $CHAIN_NAME)"
$FS script/DeployERC6551Registry.s.sol:DeployERC6551Registry --broadcast 2>&1 | grep -E "registry:|code size|ONCHAIN EXECUTION COMPLETE|Error"
expect ok "registry on fork"
ACCT_OUT=$($FS script/DeployERC6551Account.s.sol:DeployERC6551Account --broadcast 2>&1)
expect ok "account implementation on fork"
export ERC6551_IMPLEMENTATION=$(echo "$ACCT_OUT" | awk '/implementation: /{print $2}')
echo "registry code size now: $(cast codesize "$ERC6551_REGISTRY" --rpc-url "$LOCAL")"
echo "ERC6551_IMPLEMENTATION=$ERC6551_IMPLEMENTATION (code size $(cast codesize "$ERC6551_IMPLEMENTATION" --rpc-url "$LOCAL"))"

step "5. DRY RUN (no --broadcast): DeployBioRig, the contract-only deployment script"
$FS script/DeployBioRig.s.sol:DeployBioRig 2>&1
expect ok "BioRig deployment simulated with read-back"

step "6. FORK SMOKE TEST: broadcast DeployBioRig to the fork, then mint one tree"
OUT=$($FS script/DeployBioRig.s.sol:DeployBioRig --broadcast 2>&1)
expect ok "BioRig on fork"
PROXY=$(echo "$OUT" | awk -F= '/PROXY_ADDRESS=/{print $2}')
echo "proxy on fork: $PROXY"
# anvil's default accounts carry EIP-7702 delegations on Celo (code 0xef0100...), so _safeMint to them reverts in
# onERC721Received. Mint to a fresh address with no code instead.
PLANTER=0x$(cast keccak "biorig-dry-run-planter" | cut -c27-66)
echo "planter $PLANTER code: '$(cast code "$PLANTER" --rpc-url "$LOCAL")'   (anvil #1 code: '$(cast code "$BUFFER_POOL" --rpc-url "$LOCAL")')"
VERIFIER_ROLE=$(cast keccak "VERIFIER_ROLE")
UPGRADER_ROLE=$(cast keccak "UPGRADER_ROLE")
ADMIN_ROLE=0x0000000000000000000000000000000000000000000000000000000000000000
same "$(cast call "$PROXY" "hasRole(bytes32,address)(bool)" "$VERIFIER_ROLE" "$ADMIN" --rpc-url "$LOCAL")" true \
    "the deploy script granted VERIFIER_ROLE to the admin"
cast send "$PROXY" "mintTree(address,bytes32,uint96,uint96)" "$PLANTER" "$(cast keccak plot-1)" 10 20 \
    --private-key "$PRIVATE_KEY" --rpc-url "$LOCAL" | grep -E "^status"
expect ok "mintTree"
echo "ownerOf(1):      $(cast call "$PROXY" "ownerOf(uint256)(address)" 1 --rpc-url "$LOCAL")"
TBA=$(cast call "$PROXY" "getTreeStats(uint256)((uint96,uint96,uint64,address,bool,bytes32))" 1 --rpc-url "$LOCAL" | tr -d '() ' | cut -d, -f4)
echo "TBA $TBA token(): $(cast call "$TBA" "token()(uint256,address,uint256)" --rpc-url "$LOCAL" | tr '\n' ' ')"
echo "getTreeStats(1): $(cast call "$PROXY" "getTreeStats(uint256)((uint96,uint96,uint64,address,bool,bytes32))" 1 --rpc-url "$LOCAL")"

step "7. DeployAll, the single command a real deployment runs: dry run, then broadcast to the fork"
REGISTRY_HAD_CODE=$([ "$(cast code "$ERC6551_REGISTRY" --rpc-url "$LOCAL")" = "0x" ] && echo no || echo yes)
$FS script/DeployAll.s.sol:DeployAll >/dev/null 2>&1
expect ok "DeployAll simulated"
OUT=$($FS script/DeployAll.s.sol:DeployAll --broadcast 2>&1); RC=$?
echo "$OUT" | sed -n '/=== BioRig deployment summary ===/,$p'
check $RC ok "DeployAll on fork"
ARTIFACT="$FOUNDRY_BROADCAST/DeployAll.s.sol/$CHAIN_ID/run-latest.json"
CREATE2S=$(jq '[.transactions[] | select(.transactionType == "CREATE2")] | length' "$ARTIFACT")
echo "transactions in $ARTIFACT: $(jq -c '[.transactions[] | .transactionType + ":" + (.contractName // "-")]' "$ARTIFACT")"
# A chain that already has the canonical registry gets no CREATE2 at all; the tooling must not assume one.
same "$CREATE2S" "$([ "$REGISTRY_HAD_CODE" = yes ] && echo 0 || echo 1)" "CREATE2 count (registry had code before DeployAll: $REGISTRY_HAD_CODE)"
PROXY=$(echo "$OUT" | awk -F= '/PROXY_ADDRESS=/{print $2}')
echo "DeployAll proxy on fork: $PROXY"
python3 scripts/record_deployment.py --chain-id "$CHAIN_ID" --broadcast "$ARTIFACT" \
    --deployment-file "cache/fork-dry-run/deployment-$CHAIN_ID.json" --replace 2>&1 | head -2
expect ok "record_deployment.py accepts the fork artifact (written to cache/, not dashboard/)"

step "8. LOCAL FORK SETUP ONLY: a 1-of-1 Safe owned by anvil #3, to stand in for the real admin Safe"
SETUP=$(cast calldata "setup(address[],uint256,address,bytes,address,address,uint256,address)" \
    "[$SAFE_OWNER]" 1 $ZERO 0x $SAFE_FALLBACK_HANDLER $ZERO 0 $ZERO)
SALT_NONCE=$(date +%s)
SAFE=$(cast call $SAFE_FACTORY "createProxyWithNonce(address,bytes,uint256)(address)" $SAFE_L2_SINGLETON "$SETUP" \
    "$SALT_NONCE" --from "$SAFE_OWNER" --rpc-url "$LOCAL")
cast send $SAFE_FACTORY "createProxyWithNonce(address,bytes,uint256)" $SAFE_L2_SINGLETON "$SETUP" "$SALT_NONCE" \
    --private-key "$SAFE_OWNER_KEY" --rpc-url "$LOCAL" | grep -E "^status"
expect ok "Safe created on fork"
echo "Safe $SAFE: threshold $(cast call "$SAFE" "getThreshold()(uint256)" --rpc-url "$LOCAL"), owners $(cast call "$SAFE" "getOwners()(address[])" --rpc-url "$LOCAL")"
export PROXY_ADDRESS=$PROXY NEW_ADMIN=$SAFE VERIFIER_ADDRESS

step "9. GUARDS: HardenMainnetAdmin must refuse a wrong chain, a verifier that is the admin, and an admin that is not a Safe the deployer cannot sign for"
OUT=$(CHAIN_ID=44787 $FS script/HardenMainnetAdmin.s.sol:HardenMainnetAdmin 2>&1); RC=$?
check $RC fail "wrong CHAIN_ID refused"; has "$OUT" "CHAIN_ID mismatch" "by the chain-id guard"
OUT=$(VERIFIER_ADDRESS=$SAFE $FS script/HardenMainnetAdmin.s.sol:HardenMainnetAdmin 2>&1); RC=$?
check $RC fail "VERIFIER_ADDRESS == NEW_ADMIN refused"; has "$OUT" "the verifier key must not be the admin" "by the decoupling guard"
NO_CODE=0x$(cast keccak "biorig-dry-run-no-code" | cut -c27-66)
OUT=$(NEW_ADMIN=$NO_CODE $FS script/HardenMainnetAdmin.s.sol:HardenMainnetAdmin 2>&1); RC=$?
check $RC fail "NEW_ADMIN without code refused"; has "$OUT" "NEW_ADMIN has no code on this chain" "by the Safe guard"
OUT=$(NEW_ADMIN=$ERC6551_IMPLEMENTATION $FS script/HardenMainnetAdmin.s.sol:HardenMainnetAdmin 2>&1); RC=$?
check $RC fail "NEW_ADMIN that is a contract but not a Safe refused"; has "$OUT" "it is not a Safe" "by the Safe guard"
DEPLOYER_SETUP=$(cast calldata "setup(address[],uint256,address,bytes,address,address,uint256,address)" \
    "[$ADMIN]" 1 $ZERO 0x $SAFE_FALLBACK_HANDLER $ZERO 0 $ZERO)
DEPLOYER_SAFE=$(cast call $SAFE_FACTORY "createProxyWithNonce(address,bytes,uint256)(address)" $SAFE_L2_SINGLETON \
    "$DEPLOYER_SETUP" "$SALT_NONCE" --from "$SAFE_OWNER" --rpc-url "$LOCAL")
cast send $SAFE_FACTORY "createProxyWithNonce(address,bytes,uint256)" $SAFE_L2_SINGLETON "$DEPLOYER_SETUP" \
    "$SALT_NONCE" --private-key "$SAFE_OWNER_KEY" --rpc-url "$LOCAL" >/dev/null
OUT=$(NEW_ADMIN=$DEPLOYER_SAFE $FS script/HardenMainnetAdmin.s.sol:HardenMainnetAdmin 2>&1); RC=$?
check $RC fail "a Safe the deployer owns refused"; has "$OUT" "the deployer is an owner of the NEW_ADMIN Safe" "by the owner guard"
OUT=$(PROXY_ADDRESS=$ERC6551_IMPLEMENTATION $FS script/HardenMainnetAdmin.s.sol:HardenMainnetAdmin 2>&1); RC=$?
check $RC fail "a PROXY_ADDRESS that is not a BioRig proxy refused"

step "10. HANDOVER: HardenMainnetAdmin dry run, then broadcast to the fork"
$FS script/HardenMainnetAdmin.s.sol:HardenMainnetAdmin >/dev/null 2>&1
expect ok "handover simulated"
OUT=$($FS script/HardenMainnetAdmin.s.sol:HardenMainnetAdmin --broadcast 2>&1); RC=$?
echo "$OUT" | sed -n '/== Logs ==/,/The deployer key now controls nothing/p'
check $RC ok "handover broadcast to fork"
role() { cast call "$PROXY" "hasRole(bytes32,address)(bool)" "$1" "$2" --rpc-url "$LOCAL"; }
echo "on-chain read-back from the fork after the broadcast:"
for who in "deployer:$ADMIN" "Safe:$SAFE" "verifier:$VERIFIER_ADDRESS"; do
    echo "  ${who%%:*}  admin=$(role $ADMIN_ROLE "${who#*:}") upgrader=$(role "$UPGRADER_ROLE" "${who#*:}") verifier=$(role "$VERIFIER_ROLE" "${who#*:}")"
done
same "$(role $ADMIN_ROLE "$ADMIN")$(role "$UPGRADER_ROLE" "$ADMIN")$(role "$VERIFIER_ROLE" "$ADMIN")" falsefalsefalse "deployer holds nothing"
same "$(role $ADMIN_ROLE "$SAFE")$(role "$UPGRADER_ROLE" "$SAFE")$(role "$VERIFIER_ROLE" "$SAFE")" truetruefalse "Safe holds admin + upgrader only"
same "$(role $ADMIN_ROLE "$VERIFIER_ADDRESS")$(role "$UPGRADER_ROLE" "$VERIFIER_ADDRESS")$(role "$VERIFIER_ROLE" "$VERIFIER_ADDRESS")" falsefalsetrue "verifier holds VERIFIER_ROLE only"

# This gate exercises mode A: a dedicated VERIFIER_ADDRESS, so the deployer really is stripped. The mainnet run is
# mode B (the deployer key keeps VERIFIER_ROLE); script/handover-fork-check.sh rehearses that.
step "11. AFTER THE HANDOVER: the deployer is powerless, the verifier mints, the Safe administers"
cast send "$PROXY" "mintTree(address,bytes32,uint96,uint96)" "$PLANTER" "$(cast keccak plot-2)" 10 20 \
    --private-key "$PRIVATE_KEY" --rpc-url "$LOCAL" >/dev/null 2>&1
expect fail "deployer can no longer mint"
cast send "$PROXY" "pause()" --private-key "$PRIVATE_KEY" --rpc-url "$LOCAL" >/dev/null 2>&1
expect fail "deployer can no longer pause"
cast send "$PROXY" "mintTree(address,bytes32,uint96,uint96)" "$PLANTER" "$(cast keccak plot-2)" 10 20 \
    --private-key "$VERIFIER_KEY" --rpc-url "$LOCAL" | grep -E "^status"
expect ok "verifier key mints"
TBA=$(cast call "$PROXY" "getTreeStats(uint256)((uint96,uint96,uint64,address,bool,bytes32))" 1 --rpc-url "$LOCAL" | tr -d '() ' | cut -d, -f4)
BOUND_CHAIN=$(cast call "$TBA" "token()(uint256,address,uint256)" --rpc-url "$LOCAL" | head -1 | awk '{print $1}')
same "$BOUND_CHAIN" "$CHAIN_ID" "the new tree's TBA is bound to chain $CHAIN_ID"
# 1-of-1 Safe, sent by its owner: an "approved hash" signature (r = owner, s = 0, v = 1) needs no off-chain signing.
SIG=0x000000000000000000000000${SAFE_OWNER:2}000000000000000000000000000000000000000000000000000000000000000001
cast send "$SAFE" "execTransaction(address,uint256,bytes,uint8,uint256,uint256,uint256,address,address,bytes)" \
    "$PROXY" 0 "$(cast calldata 'pause()')" 0 0 0 0 $ZERO $ZERO "$SIG" \
    --private-key "$SAFE_OWNER_KEY" --rpc-url "$LOCAL" | grep -E "^status"
expect ok "Safe executes pause() through execTransaction"
same "$(cast call "$PROXY" "paused()(bool)" --rpc-url "$LOCAL")" true "proxy paused by the Safe"

step "12. GUARD: a second HardenMainnetAdmin run must refuse (the deployer has nothing left to hand over)"
OUT=$($FS script/HardenMainnetAdmin.s.sol:HardenMainnetAdmin 2>&1); RC=$?
check $RC fail "re-run refused"; has "$OUT" "does not hold DEFAULT_ADMIN_ROLE on this proxy" "by the nothing-to-hand-over guard"

step "SUMMARY ($CHAIN_NAME, chain $CHAIN_ID)"
[ $FAILED -eq 0 ] && echo "all steps behaved as expected" || echo "SOME STEPS DID NOT BEHAVE AS EXPECTED"
exit $FAILED
