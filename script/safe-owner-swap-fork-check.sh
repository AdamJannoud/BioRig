#!/usr/bin/env bash
# Rehearse the Safe owner swap (script/SafeOwnerSwap.s.sol) and the role handover it unblocks, against a fork of Celo
# mainnet at $FORK_BLOCK, with the real deployer key as the local sender. Nothing is broadcast to the real chain: anvil
# is forked, every --broadcast goes to the fork, anvil stops.
#
# Forked at $FORK_BLOCK, not at the tip: both operations EXECUTED on mainnet on 1 October 2026 (swap tx 0x7a99f809…,
# block 78991457), so the tip no longer holds the state this rehearsal rests on: the Safe is owned by
# 0xD314e37FD8538fe66231EE670B74C9428d03feEa and the deployer holds neither admin nor upgrader. Override FORK_BLOCK to
# rehearse against another state.
#
# FORK_URL must be an ARCHIVE endpoint. A fork at a historical block makes anvil fetch chain state at that block, and
# the public Celo RPCs serve historical state only intermittently (measured 2 October 2026, see the gate below), so a
# pinned fork cannot be built from them. Without an archive endpoint this script exits 2 before asserting anything.
# FORK_BLOCK=tip forks the tip instead, where the fork facts below FAIL by design: the swap has already run.
#
#   a) fork facts, asserted: at that block the Safe is SafeL2 1.5.0, 1-of-1, owned by the deployer alone, nonce 0
#   b) the swap preflight: every guard must refuse, each on its own fixture
#   c) the real swap on the forked live Safe, NEW_OWNER = a fresh stand-in EOA
#   d) read-backs: owners, threshold, nonce, deployer gone
#   e) negative control: the deployer signs a further Safe transaction, which must revert GS026
#   f) positive control: the stand-in signs one, which must succeed
#   g) the payoff, same fork: HardenMainnetAdmin in mode B with NEW_ADMIN = the swapped Safe, end state by hasRole
# plus a self-test proving the refusal checker can fail.
set -uo pipefail
cd "$(dirname "$0")/.."
export HOME=/root
CHAIN_ID=42220
FORK_URL=$(python3 -m dashboard.config get rpc_url --chain-id 42220)
PROXY=0x04Db169dDF8AbB80943161C01B2a71DC40384E64
LIVE_SAFE=0x3B36b3446fCB0729B0046520156933E56352D551       # the Safe to swap: at the pinned block, sole owner the deployer
DEPLOYER_OWNED_SAFE=0xe7042bC31A13E4FD2D5C4176ec52D28907E1311E  # the other 1 October Safe, same shape, a fixture here
EXPECTED_DEPLOYER=0x1DB0084Db70bF8D0E06c1785D693Fc6a95317890
EXPECTED_MASTER_COPY=0xEdd160fEBBD92E350D4D398fb636302fccd67C7e
PORT=${FORK_PORT:-8551}
LOCAL="http://127.0.0.1:$PORT"
KEY=${KEY_FILE:-/tmp/biorig-audit/deployer.key}
FORK_BLOCK=${FORK_BLOCK-78991456}   # the block before the swap executed (78991457); see the header
FORK_LABEL="block $FORK_BLOCK"
FORK_ARGS=(--fork-block-number "$FORK_BLOCK")
case "$FORK_BLOCK" in
    "" | tip | latest)   # an unpinned anvil forks the tip; anvil rejects a literal "latest" as a block number
        FORK_BLOCK=tip; FORK_LABEL="the chain tip"; FORK_ARGS=() ;;
esac

anvil --fork-url "$FORK_URL" --port "$PORT" "${FORK_ARGS[@]}" --silent &
ANVIL_PID=$!
trap 'kill $ANVIL_PID 2>/dev/null; wait $ANVIL_PID 2>/dev/null; echo "[anvil stopped]"' EXIT
# Anvil builds a pinned fork's genesis from ~28 consecutive historical-state reads at $FORK_BLOCK. The public Celo RPCs
# answer those only intermittently (forno about half the time, 1rpc/blockpi/thirdweb/onfinality none of the time), so a
# fork at a past block needs an archive endpoint. Fail with that reason here, rather than letting the facts gate below
# blame the fork's contents for a fork that never came up.
FORK_UP=0
for _ in $(seq 1 60); do
    if cast chain-id --rpc-url "$LOCAL" >/dev/null 2>&1; then FORK_UP=1; break; fi
    kill -0 "$ANVIL_PID" 2>/dev/null || break   # anvil is gone; waiting out the rest of the loop would prove nothing
    sleep 0.5
done
if [ "$FORK_UP" -eq 0 ]; then
    echo "FATAL: no fork of Celo mainnet at $FORK_LABEL; anvil could not build one from $FORK_URL"
    if [ "$FORK_BLOCK" != tip ]; then
        echo "       Historical chain state is what anvil needs at a past block and what the public Celo RPCs do not serve."
        echo "       Set FORK_URL to an archive endpoint to rehearse against a past block."
    fi
    echo "       Nothing was asserted: this is an environment gap, not a mismatch in the on-chain facts."
    exit 2
fi

export FOUNDRY_BROADCAST=cache/safe-owner-swap-fork-check/broadcast
export PRIVATE_KEY=$(cat "$KEY")
export CHAIN_ID PROXY_ADDRESS="$PROXY"
DEPLOYER=$(cast wallet address --private-key "$PRIVATE_KEY")
if [ "$DEPLOYER" != "$EXPECTED_DEPLOYER" ]; then
    echo "FATAL: the key in $KEY derives to $DEPLOYER, not the deployer $EXPECTED_DEPLOYER"; exit 1
fi
ZERO=0x0000000000000000000000000000000000000000
ADMIN_ROLE=0x0000000000000000000000000000000000000000000000000000000000000000
UPGRADER_ROLE=$(cast keccak UPGRADER_ROLE)
VERIFIER_ROLE=$(cast keccak VERIFIER_ROLE)
SAFE_FACTORY=0x4e1DCf7AD4e460CfD30791CCC4F9c8a4f820ec67
SAFE_L2_SINGLETON=0x29fcB43b46531BcA003ddC8FCB67FFE91900C762
SAFE_FALLBACK_HANDLER=0xfd0732Dc9E303f09fCEf3a7388Ad10A83459Ec99
SAFE_TX_HASH_SIG="getTransactionHash(address,uint256,bytes,uint8,uint256,uint256,uint256,address,address,uint256)(bytes32)"
SAFE_EXEC_SIG="execTransaction(address,uint256,bytes,uint8,uint256,uint256,uint256,address,address,bytes)"
FAILED=0

first() { awk 'NR==1{print $1}' | tr -d '"'; }   # first token of cast output: drops "[1e3]" annotations and quotes
rd() { cast call "$@" --rpc-url "$LOCAL" 2>&1 | first; }
owners() { cast call "$1" "getOwners()(address[])" --rpc-url "$LOCAL"; }
lc() { tr '[:upper:]' '[:lower:]'; }
rol() { cast call "$PROXY" "hasRole(bytes32,address)(bool)" "$1" "$2" --rpc-url "$LOCAL" | tr -d '[:space:]'; }

check() { # check <label> <actual> <expected>
    if [ "$2" = "$3" ]; then echo "  PASS  $1 = $2"
    else echo "  FAIL  $1 = $2 (expected $3)"; FAILED=$((FAILED + 1)); fi
}

guard() { # guard <label> <expected-substring-or-empty> [VAR=value ...]: the swap must refuse, nothing is broadcast
    local label=$1 want=$2; shift 2
    local out rc
    out=$(env "$@" forge script --rpc-url "$LOCAL" script/SafeOwnerSwap.s.sol:SafeOwnerSwap 2>&1); rc=$?
    if [ $rc -ne 0 ] && { [ -z "$want" ] || printf '%s' "$out" | grep -qF "$want"; }; then
        echo "  PASS  $label refused (exit $rc): $(printf '%s' "$out" | grep -m1 -oE 'script failed: .*' | cut -c1-160)"
    else
        echo "  FAIL  $label exit=$rc (wanted refusal matching: ${want:-any})"
        printf '%s' "$out" | grep -E "script failed|Error" | head -2
        FAILED=$((FAILED + 1))
    fi
}

new_safe() { # new_safe <owner[,owner...]> <threshold> <salt> -> prints the address of the v1.4.1 SafeL2 it creates
    local setup addr
    setup=$(cast calldata "setup(address[],uint256,address,bytes,address,address,uint256,address)" \
        "[$1]" "$2" $ZERO 0x $SAFE_FALLBACK_HANDLER $ZERO 0 $ZERO)
    addr=$(cast call $SAFE_FACTORY "createProxyWithNonce(address,bytes,uint256)(address)" \
        $SAFE_L2_SINGLETON "$setup" "$3" --from "$STANDIN" --rpc-url "$LOCAL")
    cast send $SAFE_FACTORY "createProxyWithNonce(address,bytes,uint256)" $SAFE_L2_SINGLETON "$setup" "$3" \
        --private-key "$STANDIN_KEY" --rpc-url "$LOCAL" >/dev/null || return 1
    printf '%s' "$addr"
}

safe_self_tx() { # safe_self_tx <safe> <signer-key> <calldata>: a Safe transaction to itself, signed and sent by one key
    local safe=$1 key=$2 data=$3 nonce hash sig
    nonce=$(rd "$safe" "nonce()(uint256)")
    hash=$(rd "$safe" "$SAFE_TX_HASH_SIG" "$safe" 0 "$data" 0 0 0 0 $ZERO $ZERO "$nonce")
    sig=$(cast wallet sign --no-hash "$hash" --private-key "$key")
    cast send "$safe" "$SAFE_EXEC_SIG" "$safe" 0 "$data" 0 0 0 0 $ZERO $ZERO "$sig" \
        --private-key "$key" --rpc-url "$LOCAL" 2>&1
}

echo "### a) fork facts"
echo "fork chain id: $(cast chain-id --rpc-url "$LOCAL")   fork block: $(cast block-number --rpc-url "$LOCAL")"
check "fork chain id" "$(cast chain-id --rpc-url "$LOCAL")" 42220
case "$FORK_BLOCK" in
    *[!0-9]*) echo "  SKIP  fork pinned to the pre-swap block (FORK_BLOCK=$FORK_BLOCK is not a block number)" ;;
    *) check "fork pinned to the pre-swap block" "$(cast block-number --rpc-url "$LOCAL")" "$FORK_BLOCK" ;;
esac
SAFE_CODE_SIZE=$(cast codesize "$LIVE_SAFE" --rpc-url "$LOCAL" 2>/dev/null)
check "live Safe $LIVE_SAFE has code (size > 0)" "$([ "${SAFE_CODE_SIZE:-0}" -gt 0 ] && echo yes)" yes
echo "        live Safe code size: $SAFE_CODE_SIZE"
check "live Safe VERSION()" "$(rd "$LIVE_SAFE" "VERSION()(string)")" 1.5.0
check "live Safe masterCopy (slot 0)" "0x$(cast storage "$LIVE_SAFE" 0 --rpc-url "$LOCAL" | cut -c27-66)" "$(echo "$EXPECTED_MASTER_COPY" | lc)"
check "live Safe getThreshold()" "$(rd "$LIVE_SAFE" "getThreshold()(uint256)")" 1
check "live Safe getOwners()" "$(owners "$LIVE_SAFE")" "[$DEPLOYER]"
check "live Safe nonce()" "$(rd "$LIVE_SAFE" "nonce()(uint256)")" 0
check "deployer code size (code-less EOA)" "$(cast codesize "$DEPLOYER" --rpc-url "$LOCAL")" 0
check "fixture Safe $DEPLOYER_OWNED_SAFE owners" "$(owners "$DEPLOYER_OWNED_SAFE")" "[$DEPLOYER]"
echo "sender (real deployer key, local only) $DEPLOYER  balance $(cast balance "$DEPLOYER" --rpc-url "$LOCAL")"

# Stand-ins: fresh keys every run. Never the well-known anvil mnemonic accounts: on Celo mainnet they carry EIP-7702
# delegations (0xef0100 designators, 23 bytes of code), which the code-less requirement would rightly refuse.
STANDIN_KEY=0x$(openssl rand -hex 32)
STANDIN=$(cast wallet address --private-key "$STANDIN_KEY")
OTHER_KEY=0x$(openssl rand -hex 32)
OTHER=$(cast wallet address --private-key "$OTHER_KEY")
echo "stand-in NEW_OWNER $STANDIN   second stand-in $OTHER (fresh keys, this run only)"
check "stand-in code size (code-less)" "$(cast codesize "$STANDIN" --rpc-url "$LOCAL")" 0
check "second stand-in code size (code-less)" "$(cast codesize "$OTHER" --rpc-url "$LOCAL")" 0
if [ "$FAILED" -ne 0 ]; then echo "FATAL: the fork does not match the facts this rehearsal rests on"; exit 1; fi
cast rpc anvil_setBalance "$STANDIN" 0xde0b6b3a7640000 --rpc-url "$LOCAL" >/dev/null

export SAFE_ADDRESS=$LIVE_SAFE NEW_OWNER=$STANDIN
SALT=$(date +%s)

echo
echo "### before the swap: the handover is blocked on this Safe"
OUT=$(env NEW_ADMIN="$LIVE_SAFE" VERIFIER_ADDRESS="$DEPLOYER" \
    forge script --rpc-url "$LOCAL" script/HardenMainnetAdmin.s.sol:HardenMainnetAdmin 2>&1); RC=$?
if [ $RC -ne 0 ] && printf '%s' "$OUT" | grep -qF "the deployer is an owner of the NEW_ADMIN Safe"; then
    echo "  PASS  handover refused (exit $RC): $(printf '%s' "$OUT" | grep -m1 -oE 'script failed: .*' | cut -c1-120)"
else
    echo "  FAIL  handover with NEW_ADMIN=$LIVE_SAFE exit=$RC (wanted the deployer-owner refusal)"; FAILED=$((FAILED + 1))
fi

echo
echo "### b) swap preflight guards (each must refuse; nothing is signed or broadcast)"
guard "NEW_OWNER is the deployer" "NEW_OWNER is the deployer" "NEW_OWNER=$DEPLOYER"
guard "NEW_OWNER is the zero address" "NEW_OWNER is the zero address" "NEW_OWNER=$ZERO"

TWO_OWNER_SAFE=$(new_safe "$DEPLOYER,$OTHER" 1 $((SALT + 1))) || exit 1
echo "  fixture: 1-of-2 Safe $TWO_OWNER_SAFE owners $(owners "$TWO_OWNER_SAFE")"
guard "NEW_OWNER already an owner" "NEW_OWNER is already an owner of this Safe" \
    "SAFE_ADDRESS=$TWO_OWNER_SAFE" "NEW_OWNER=$OTHER"
guard "deployer one of two owners (not sole)" "not the sole owner" "SAFE_ADDRESS=$TWO_OWNER_SAFE"

# The trap from 1 October 2026: handing the Safe to another Safe the hot key owns.
DEPLOYER_SAFE=$(new_safe "$DEPLOYER" 1 $((SALT + 2))) || exit 1
echo "  fixture: fresh 1-of-1 Safe owned by the deployer $DEPLOYER_SAFE owners $(owners "$DEPLOYER_SAFE")"
guard "NEW_OWNER is a Safe the deployer owns" "the deployer is an owner of the NEW_OWNER Safe" \
    "NEW_OWNER=$DEPLOYER_SAFE"
NESTED_SAFE=$(new_safe "$DEPLOYER_OWNED_SAFE" 1 $((SALT + 3))) || exit 1
echo "  fixture: Safe $NESTED_SAFE owned by $DEPLOYER_OWNED_SAFE (deployer one level down)"
guard "NEW_OWNER owned by a Safe the deployer owns" "an owner of the NEW_OWNER Safe is owned by the deployer" \
    "NEW_OWNER=$NESTED_SAFE"
guard "NEW_OWNER a contract that cannot be inspected" "NEW_OWNER is a contract this script cannot inspect" \
    "NEW_OWNER=$PROXY"
echo "  ALLOW_UNINSPECTED_OWNER override, positive control (a dry run, nothing broadcast):"
OUT=$(env NEW_OWNER="$PROXY" ALLOW_UNINSPECTED_OWNER=true \
    forge script --rpc-url "$LOCAL" script/SafeOwnerSwap.s.sol:SafeOwnerSwap 2>&1); RC=$?
if [ $RC -eq 0 ] && printf '%s' "$OUT" | grep -qF "WARNING: uninspected contract NEW_OWNER accepted"; then
    echo "  PASS  override accepted an uninspected contract NEW_OWNER, and said so"
else
    echo "  FAIL  override path exit=$RC (wanted exit 0 and the warning line)"
    printf '%s' "$OUT" | grep -E "script failed|Error" | head -2
    FAILED=$((FAILED + 1))
fi

guard "SAFE_ADDRESS is not a Safe (the BioRig proxy)" "SAFE_ADDRESS does not answer getThreshold(); it is not a Safe" \
    "SAFE_ADDRESS=$PROXY"
guard "SAFE_ADDRESS without code" "SAFE_ADDRESS has no code on this chain" "SAFE_ADDRESS=$ZERO"
TWO_OF_TWO=$(new_safe "$DEPLOYER,$OTHER" 2 $((SALT + 4))) || exit 1
echo "  fixture: 2-of-2 Safe $TWO_OF_TWO owners $(owners "$TWO_OF_TWO") threshold $(rd "$TWO_OF_TWO" "getThreshold()(uint256)")"
guard "2-of-2 Safe (threshold)" "not 1: a swapOwner signed by the deployer alone cannot satisfy it" \
    "SAFE_ADDRESS=$TWO_OF_TWO"
FOREIGN_SAFE=$(new_safe "$OTHER" 1 $((SALT + 5))) || exit 1
echo "  fixture: Safe $FOREIGN_SAFE owned by someone else $(owners "$FOREIGN_SAFE")"
guard "Safe the deployer does not own" "the deployer key cannot sign for this Safe; nothing to swap" \
    "SAFE_ADDRESS=$FOREIGN_SAFE"
guard "wrong PRIVATE_KEY" "the deployer key cannot sign for this Safe; nothing to swap" "PRIVATE_KEY=$OTHER_KEY"
guard "wrong CHAIN_ID" "CHAIN_ID mismatch" "CHAIN_ID=11142220"
check "live Safe nonce after the guards (nothing executed)" "$(rd "$LIVE_SAFE" "nonce()(uint256)")" 0
echo "  preflight failures so far: $FAILED"

echo
echo "### harness self-test (a check that cannot fail is not a check)"
# 1. A config the swap accepts, fed to the refusal checker: it must report FAIL. Run in a subshell so the deliberate
#    failure does not count against this rehearsal; nothing is broadcast (guard never passes --broadcast).
SELF=$(guard "self-test: valid config" "" 2>&1; echo "inner FAILED=$FAILED")
if printf '%s' "$SELF" | grep -q "^  FAIL  self-test: valid config"; then
    echo "  PASS  the refusal checker reports FAIL when the swap does NOT refuse"
else echo "  FAIL  the refusal checker passed a config the swap accepts"; FAILED=$((FAILED + 1)); fi
# 2. A real refusal for the wrong reason: the substring match must catch it.
SELF=$(guard "self-test: wrong reason" "the deployer is an owner of the NEW_OWNER Safe" "NEW_OWNER=$DEPLOYER" 2>&1)
if printf '%s' "$SELF" | grep -q "^  FAIL  self-test: wrong reason"; then
    echo "  PASS  the refusal checker reports FAIL when the refusal is for a different reason"
else echo "  FAIL  the refusal checker accepted a refusal for the wrong reason"; FAILED=$((FAILED + 1)); fi
# 3. check() itself.
SELF=$(check "self-test: mismatch" a b)
if printf '%s' "$SELF" | grep -q "^  FAIL"; then echo "  PASS  check() reports FAIL on a mismatch"
else echo "  FAIL  check() passed a mismatch"; FAILED=$((FAILED + 1)); fi

echo
echo "### c) the swap: dry run, then broadcast to the fork"
OUT=$(forge script --rpc-url "$LOCAL" script/SafeOwnerSwap.s.sol:SafeOwnerSwap 2>&1); RC=$?
echo "dry-run exit=$RC"
check "dry run left the live Safe untouched (nonce)" "$(rd "$LIVE_SAFE" "nonce()(uint256)")" 0
OUT=$(forge script --rpc-url "$LOCAL" script/SafeOwnerSwap.s.sol:SafeOwnerSwap --broadcast 2>&1); RC=$?
echo "$OUT" | sed -n '/== Logs ==/,/^$/p'
echo "$OUT" | grep -E "ONCHAIN EXECUTION COMPLETE|Status|Transactions saved" | head -4
check "swap broadcast exit" "$RC" 0

echo
echo "### d) read-back from the fork"
check "owners" "$(owners "$LIVE_SAFE")" "[$STANDIN]"
check "threshold" "$(rd "$LIVE_SAFE" "getThreshold()(uint256)")" 1
check "nonce" "$(rd "$LIVE_SAFE" "nonce()(uint256)")" 1
check "isOwner(deployer)" "$(rd "$LIVE_SAFE" "isOwner(address)(bool)" "$DEPLOYER")" false
check "isOwner(stand-in)" "$(rd "$LIVE_SAFE" "isOwner(address)(bool)" "$STANDIN")" true
guard "second swap run (re-run safety)" "the deployer key cannot sign for this Safe; nothing to swap"

echo
echo "### e) negative control: the deployer signs changeThreshold(1) - must revert GS026"
DATA=$(cast calldata "changeThreshold(uint256)" 1)
OUT=$(safe_self_tx "$LIVE_SAFE" "$PRIVATE_KEY" "$DATA"); RC=$?
if [ $RC -ne 0 ] && printf '%s' "$OUT" | grep -q "GS026"; then
    echo "  PASS  deployer-signed Safe transaction refused (exit $RC): $(printf '%s' "$OUT" | grep -m1 -oE 'execution reverted: GS026' || echo GS026)"
else
    echo "  FAIL  deployer-signed Safe transaction exit=$RC (wanted a GS026 revert)"
    printf '%s' "$OUT" | head -3
    FAILED=$((FAILED + 1))
fi
check "nonce unchanged by the refused transaction" "$(rd "$LIVE_SAFE" "nonce()(uint256)")" 1

echo
echo "### f) positive control: the stand-in signs changeThreshold(1) - must succeed"
OUT=$(safe_self_tx "$LIVE_SAFE" "$STANDIN_KEY" "$DATA"); RC=$?
printf '%s\n' "$OUT" | grep -E "^status" | sed 's/^/        /'
check "stand-in Safe transaction exit" "$RC" 0
check "stand-in Safe transaction status" "$(printf '%s' "$OUT" | awk '/^status/{print $2}')" 1
check "nonce after the stand-in's transaction" "$(rd "$LIVE_SAFE" "nonce()(uint256)")" 2
check "owners still [stand-in]" "$(owners "$LIVE_SAFE")" "[$STANDIN]"

echo
echo "### g) the payoff, same fork: HardenMainnetAdmin mode B with NEW_ADMIN = the swapped Safe"
export NEW_ADMIN=$LIVE_SAFE VERIFIER_ADDRESS=$DEPLOYER
BUFFER_BEFORE=$(rd "$PROXY" "bufferPool()(address)")
echo "  before: deployer admin=$(rol $ADMIN_ROLE "$DEPLOYER") upgrader=$(rol "$UPGRADER_ROLE" "$DEPLOYER") verifier=$(rol "$VERIFIER_ROLE" "$DEPLOYER")   bufferPool=$BUFFER_BEFORE"
OUT=$(forge script --rpc-url "$LOCAL" script/HardenMainnetAdmin.s.sol:HardenMainnetAdmin 2>&1); RC=$?
check "handover dry run exit" "$RC" 0
OUT=$(forge script --rpc-url "$LOCAL" script/HardenMainnetAdmin.s.sol:HardenMainnetAdmin --broadcast 2>&1); RC=$?
echo "$OUT" | sed -n '/=== BioRig role handover ===/,/^$/p'
check "handover broadcast exit" "$RC" 0

echo
echo "### end state, read back with hasRole on $PROXY"
check "deployer DEFAULT_ADMIN_ROLE" "$(rol "$ADMIN_ROLE" "$DEPLOYER")" false
check "deployer UPGRADER_ROLE" "$(rol "$UPGRADER_ROLE" "$DEPLOYER")" false
check "deployer VERIFIER_ROLE (kept, mode B)" "$(rol "$VERIFIER_ROLE" "$DEPLOYER")" true
check "Safe DEFAULT_ADMIN_ROLE" "$(rol "$ADMIN_ROLE" "$LIVE_SAFE")" true
check "Safe UPGRADER_ROLE" "$(rol "$UPGRADER_ROLE" "$LIVE_SAFE")" true
check "Safe VERIFIER_ROLE" "$(rol "$VERIFIER_ROLE" "$LIVE_SAFE")" false
check "bufferPool untouched" "$(rd "$PROXY" "bufferPool()(address)")" "$BUFFER_BEFORE"
check "Safe owners (the stand-in, not the deployer)" "$(owners "$LIVE_SAFE")" "[$STANDIN]"

echo
if [ "$FAILED" -eq 0 ]; then echo "REHEARSAL PASSED: swap + mode-B handover, 0 failures"; else echo "REHEARSAL FAILED: $FAILED check(s)"; fi
exit $FAILED
