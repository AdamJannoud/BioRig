#!/usr/bin/env bash
# Fork dry run of the deployment against real Celo Sepolia state. Starts anvil forked from Celo Sepolia, runs the
# scripts against it, and stops anvil on exit, so nothing is left running. Nothing is sent to Celo Sepolia itself.
#
# PRIVATE_KEY below is anvil's well-known account #0 key. It is PUBLIC. Use it only against this local fork and
# never for a real broadcast.
#
# Usage: script/fork-dry-run.sh [FORK_URL]
set -uo pipefail
cd "$(dirname "$0")/.."

FORK_URL="${1:-https://forno.celo-sepolia.celo-testnet.org}"
PORT=8547
LOCAL="http://127.0.0.1:$PORT"

anvil --fork-url "$FORK_URL" --port "$PORT" --silent &
ANVIL_PID=$!
trap 'kill $ANVIL_PID 2>/dev/null; wait $ANVIL_PID 2>/dev/null; echo "[anvil stopped]"' EXIT
for _ in $(seq 1 60); do cast chain-id --rpc-url "$LOCAL" >/dev/null 2>&1 && break; sleep 0.5; done

# The fork reports chain id 11142220, so without this forge would file the fork's broadcast logs under
# broadcast/<script>/11142220/, where they would look like a real Celo Sepolia deployment.
export FOUNDRY_BROADCAST=cache/fork-dry-run/broadcast
export PRIVATE_KEY=0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80 # anvil #0, local fork only
export ADMIN=0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266                                # anvil #0
export BUFFER_POOL=0x70997970C51812dc3A010C7d01b50e0d17dc79C8                          # anvil #1
export URI_GENERATOR=0x0000000000000000000000000000000000000000
export CHAIN_ID=11142220
export ERC6551_REGISTRY=0x000000006551c19487814612e58FE06813775758
export ERC6551_IMPLEMENTATION=0x4e59b44847b379578588920cA78FbF26c0B4956C # placeholder with code; replaced in step 4

step() { printf '\n\n######## %s\n' "$*"; }
expect() { # expect <ok|fail> <label>: records whether the previous command's exit status matched
    local rc=$? want=$1; shift
    if { [ "$want" = ok ] && [ $rc -eq 0 ]; } || { [ "$want" = fail ] && [ $rc -ne 0 ]; }; then
        echo ">>> AS EXPECTED ($want, exit $rc): $*"
    else
        echo ">>> UNEXPECTED (wanted $want, exit $rc): $*"; FAILED=1
    fi
}
FAILED=0
FS="forge script --rpc-url $LOCAL"

step "0. Fork facts"
echo "upstream: $FORK_URL"
echo "fork eth_chainId: $(cast chain-id --rpc-url "$LOCAL")   fork block: $(cast block-number --rpc-url "$LOCAL")"
echo "code at canonical ERC-6551 registry $ERC6551_REGISTRY: '$(cast code "$ERC6551_REGISTRY" --rpc-url "$LOCAL")'"
echo "code size at Nick's factory 0x4e59b448...: $(cast codesize 0x4e59b44847b379578588920cA78FbF26c0B4956C --rpc-url "$LOCAL")"

step "1. GUARD: DeployBioRig with the canonical registry, which has no code on Celo Sepolia (must refuse)"
$FS script/DeployBioRig.s.sol:DeployBioRig 2>&1
expect fail "registry-code guard fired"

step "2. GUARD: DeployBioRig with CHAIN_ID=44787 (Alfajores) against a Celo Sepolia RPC (must refuse)"
CHAIN_ID=44787 $FS script/DeployBioRig.s.sol:DeployBioRig 2>&1
expect fail "chain-id guard fired"

step "3. DRY RUN (no --broadcast): DeployERC6551Registry, canonical mode"
$FS script/DeployERC6551Registry.s.sol:DeployERC6551Registry 2>&1
expect ok "registry deployment simulated"

step "4. LOCAL FORK SETUP ONLY: broadcast the registry and example account to the anvil fork (not Celo Sepolia)"
$FS script/DeployERC6551Registry.s.sol:DeployERC6551Registry --broadcast 2>&1 | grep -E "registry:|code size|ONCHAIN EXECUTION COMPLETE|Error"
expect ok "registry on fork"
ACCT_OUT=$($FS script/DeployERC6551Account.s.sol:DeployERC6551Account --broadcast 2>&1)
expect ok "account implementation on fork"
export ERC6551_IMPLEMENTATION=$(echo "$ACCT_OUT" | awk '/implementation: /{print $2}')
echo "registry code size now: $(cast codesize "$ERC6551_REGISTRY" --rpc-url "$LOCAL")"
echo "ERC6551_IMPLEMENTATION=$ERC6551_IMPLEMENTATION (code size $(cast codesize "$ERC6551_IMPLEMENTATION" --rpc-url "$LOCAL"))"

step "5. DRY RUN (no --broadcast): DeployBioRig, the real deployment script"
$FS script/DeployBioRig.s.sol:DeployBioRig 2>&1
expect ok "BioRig deployment simulated with read-back"

step "6. FORK SMOKE TEST: broadcast DeployBioRig to the fork, then grant VERIFIER_ROLE and mint one tree"
OUT=$($FS script/DeployBioRig.s.sol:DeployBioRig --broadcast 2>&1)
expect ok "BioRig on fork"
PROXY=$(echo "$OUT" | awk '/proxy \(use this address\):/{print $NF}')
echo "proxy on fork: $PROXY"
# anvil's default accounts carry EIP-7702 delegations on Celo Sepolia (code 0xef0100...), so _safeMint to them
# reverts in onERC721Received. Mint to a fresh address with no code instead.
PLANTER=0x$(cast keccak "biorig-dry-run-planter" | cut -c27-66)
echo "planter $PLANTER code: '$(cast code "$PLANTER" --rpc-url "$LOCAL")'   (anvil #1 code: '$(cast code "$BUFFER_POOL" --rpc-url "$LOCAL")')"
VERIFIER_ROLE=$(cast keccak "VERIFIER_ROLE")
cast send "$PROXY" "grantRole(bytes32,address)" "$VERIFIER_ROLE" "$ADMIN" \
    --private-key "$PRIVATE_KEY" --rpc-url "$LOCAL" >/dev/null
expect ok "grantRole(VERIFIER_ROLE, admin)"
cast send "$PROXY" "mintTree(address,bytes32,uint96,uint96)" "$PLANTER" "$(cast keccak plot-1)" 10 20 \
    --private-key "$PRIVATE_KEY" --rpc-url "$LOCAL" | grep -E "^status"
expect ok "mintTree"
echo "ownerOf(1):      $(cast call "$PROXY" "ownerOf(uint256)(address)" 1 --rpc-url "$LOCAL")"
TBA=$(cast call "$PROXY" "getTreeStats(uint256)((uint96,uint96,uint64,address,bool,bytes32))" 1 --rpc-url "$LOCAL" | tr -d '() ' | cut -d, -f4)
echo "TBA $TBA token(): $(cast call "$TBA" "token()(uint256,address,uint256)" --rpc-url "$LOCAL" | tr '\n' ' ')"
echo "getTreeStats(1): $(cast call "$PROXY" "getTreeStats(uint256)((uint96,uint96,uint64,address,bool,bytes32))" 1 --rpc-url "$LOCAL")"

step "SUMMARY"
[ $FAILED -eq 0 ] && echo "all steps behaved as expected" || echo "SOME STEPS DID NOT BEHAVE AS EXPECTED"
exit $FAILED
