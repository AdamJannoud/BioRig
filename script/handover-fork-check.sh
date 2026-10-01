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
rol() { role "$1" "$2" | tr -d '[:space:]'; }   # same, trimmed, for comparisons
FAILED=0

check() { # check <label> <actual> <expected>
    if [ "$2" = "$3" ]; then echo "  PASS  $1 = $2"
    else echo "  FAIL  $1 = $2 (expected $3)"; FAILED=$((FAILED + 1)); fi
}

guard() { # guard <label> <expected-substring-or-empty> [VAR=value ...]: must refuse, must not broadcast
    local label=$1 want=$2; shift 2
    local out rc
    out=$(env "$@" forge script --rpc-url "$LOCAL" script/HardenMainnetAdmin.s.sol:HardenMainnetAdmin 2>&1); rc=$?
    if [ $rc -ne 0 ] && { [ -z "$want" ] || printf '%s' "$out" | grep -qF "$want"; }; then
        echo "  PASS  $label refused (exit $rc): $(printf '%s' "$out" | grep -m1 -oE 'script failed: .*' | cut -c1-120)"
    else
        echo "  FAIL  $label exit=$rc (wanted refusal matching: ${want:-any})"
        printf '%s' "$out" | grep -E "Error" | head -2
        FAILED=$((FAILED + 1))
    fi
}

send_exit() { # send_exit <label> <key> <zero|nonzero> <signature> [args...]
    local label=$1 key=$2 want=$3; shift 3
    cast send "$PROXY" "$@" --private-key "$key" --rpc-url "$LOCAL" >/dev/null 2>&1
    local rc=$?
    if [ "$want" = zero ] && [ $rc -eq 0 ]; then echo "  PASS  $label succeeded"
    elif [ "$want" = nonzero ] && [ $rc -ne 0 ]; then echo "  PASS  $label refused (exit $rc)"
    else echo "  FAIL  $label exit $rc (wanted $want)"; FAILED=$((FAILED + 1)); fi
}
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
FORK_VERIFIER=$(cast wallet address --private-key "$VERIFIER_KEY")
SAFE_OWNER_KEY=$(cast wallet private-key --mnemonic "$MNEMONIC" --mnemonic-index 3)
SAFE_OWNER=$(cast wallet address --private-key "$SAFE_OWNER_KEY")
ZERO=0x0000000000000000000000000000000000000000
SAFE_FACTORY=0x4e1DCf7AD4e460CfD30791CCC4F9c8a4f820ec67
SAFE_L2_SINGLETON=0x29fcB43b46531BcA003ddC8FCB67FFE91900C762
SAFE_FALLBACK_HANDLER=0xfd0732Dc9E303f09fCEf3a7388Ad10A83459Ec99
export NEW_ADMIN_OWNER=$SAFE_OWNER

# The owner of every stand-in Safe. It must be an address with NO code: a plain EOA the guard accepts. The well-known
# anvil/hardhat test accounts cannot serve - Celo mainnet carries EIP-7702 delegations (0xef0100||address) on all of
# them, so they have code there and the ownership walk would rightly treat them as contracts.
OWNER_STANDIN_KEY=$(cast keccak "biorig handover rehearsal stand-in owner")
OWNER_STANDIN=$(cast wallet address --private-key "$OWNER_STANDIN_KEY")
echo "stand-in owner $OWNER_STANDIN code size on the fork: $(cast codesize "$OWNER_STANDIN" --rpc-url "$LOCAL")"
if [ "$(cast codesize "$OWNER_STANDIN" --rpc-url "$LOCAL")" != "0" ]; then
    echo "FATAL: the stand-in owner has code on this fork; the ownership walk would treat it as a contract"; exit 1
fi

new_safe() { # new_safe <owner> <salt> -> prints the address of the Safe it creates
    local setup addr
    setup=$(cast calldata "setup(address[],uint256,address,bytes,address,address,uint256,address)" \
        "[$1]" 1 $ZERO 0x $SAFE_FALLBACK_HANDLER $ZERO 0 $ZERO)
    addr=$(cast call $SAFE_FACTORY "createProxyWithNonce(address,bytes,uint256)(address)" \
        $SAFE_L2_SINGLETON "$setup" "$2" --from "$SAFE_OWNER" --rpc-url "$LOCAL")
    cast send $SAFE_FACTORY "createProxyWithNonce(address,bytes,uint256)" $SAFE_L2_SINGLETON "$setup" "$2" \
        --private-key "$SAFE_OWNER_KEY" --rpc-url "$LOCAL" >/dev/null || return 1
    printf '%s' "$addr"
}

# Stand-ins by default. NEW_ADMIN_IN / VERIFIER_ADDRESS_IN rehearse the REAL addresses someone is about to use, so the
# preflight is exercised against exactly those values and not a friendlier pair.
if [ -n "${NEW_ADMIN_IN:-}" ]; then
    export NEW_ADMIN="$NEW_ADMIN_IN"
    echo "### NEW_ADMIN SUPPLIED (not a fork stand-in): $NEW_ADMIN"
    echo "    code size on the fork: $(cast codesize "$NEW_ADMIN" --rpc-url "$LOCAL")"
    echo "    getThreshold -> $(cast call "$NEW_ADMIN" "getThreshold()(uint256)" --rpc-url "$LOCAL" 2>&1 | head -1)"
    echo "    getOwners    -> $(cast call "$NEW_ADMIN" "getOwners()(address[])" --rpc-url "$LOCAL" 2>&1 | head -1)"
else
    echo "### fork stand-in: NEW_ADMIN Safe (owner $OWNER_STANDIN)"
    cast rpc anvil_setBalance "$SAFE_OWNER" 0xde0b6b3a7640000 --rpc-url "$LOCAL" >/dev/null
    SALT_NONCE=$(date +%s)
    SAFE=$(new_safe "$OWNER_STANDIN" "$SALT_NONCE") || exit 1
    export NEW_ADMIN=$SAFE
    echo "Safe $SAFE threshold $(cast call "$SAFE" "getThreshold()(uint256)" --rpc-url "$LOCAL") owners $(cast call "$SAFE" "getOwners()(address[])" --rpc-url "$LOCAL")"
fi
SAFE="$NEW_ADMIN"
export VERIFIER_ADDRESS="${VERIFIER_ADDRESS_IN:-$FORK_VERIFIER}"
# Mode A: VERIFIER_ADDRESS is its own key, so minting moves there and the deployer is stripped of it. Mode B: it is
# the deployer itself, so minting deliberately stays on the hot key (Adam's decision, 1 October 2026).
MODE=$([ "$VERIFIER_ADDRESS" = "$DEPLOYER" ] && echo B || echo A)
echo "### VERIFIER_ADDRESS $VERIFIER_ADDRESS   mode $MODE $([ "$MODE" = B ] && echo '(minting stays on the deployer)' || echo '(dedicated verifier key)')"
echo "    fork stand-in verifier key held: $([ "$VERIFIER_ADDRESS" = "$FORK_VERIFIER" ] && echo yes || echo no)"

# Guard-check mode: prove the mode-B preflight refuses a deployer that does not hold VERIFIER_ROLE, then stop.
if [ -n "${GUARD_ONLY:-}" ]; then
    echo
    echo "### guard check: mode B, deployer does not hold VERIFIER_ROLE"
    cast send "$PROXY" "renounceRole(bytes32,address)" "$VERIFIER_ROLE" "$DEPLOYER" \
        --private-key "$PRIVATE_KEY" --rpc-url "$LOCAL" | grep -E "^status"
    who deployer "$DEPLOYER"
    OUT=$(forge script --rpc-url "$LOCAL" script/HardenMainnetAdmin.s.sol:HardenMainnetAdmin 2>&1); RC=$?
    printf '%s' "$OUT" | grep -m1 -oE 'script failed: .*' | cut -c1-140
    if [ $RC -ne 0 ] && printf '%s' "$OUT" | grep -qF "does not hold VERIFIER_ROLE"; then
        echo "GUARD PASSED: mode-B preflight refused a deployer with no VERIFIER_ROLE"; exit 0
    fi
    echo "GUARD FAILED (exit $RC)"; exit 1
fi

echo
echo "### preflight guards, against the values about to be used (each must refuse; nothing is broadcast)"
ADAM_SAFE=0x3B36b3446fCB0729B0046520156933E56352D551   # Adam's Celo Safe: real, and owned by the deployer alone
SALT_NONCE=${SALT_NONCE:-$(date +%s)}

guard "NEW_ADMIN owned by the deployer" "the deployer is an owner of the NEW_ADMIN Safe" \
    "NEW_ADMIN=$ADAM_SAFE" "NEW_ADMIN_OWNER=$OWNER_STANDIN"

# The same trap one level down, and the case that actually came up on 1 October 2026: a fresh Safe whose sole owner is
# a Safe the hot key signs for. The owners-list check alone passes this, so it is the negative control for the walk.
# ADAM_OWNER_SAFE is live on the fork with the deployer as its only owner; the Safe around it is created here.
ADAM_OWNER_SAFE=0xe7042bC31A13E4FD2D5C4176ec52D28907E1311E
echo "  ADAM_OWNER_SAFE $ADAM_OWNER_SAFE threshold $(cast call "$ADAM_OWNER_SAFE" "getThreshold()(uint256)" --rpc-url "$LOCAL") owners $(cast call "$ADAM_OWNER_SAFE" "getOwners()(address[])" --rpc-url "$LOCAL")"
NESTED_ADMIN=$(new_safe "$ADAM_OWNER_SAFE" $((SALT_NONCE + 1))) || exit 1
echo "  nested stand-in $NESTED_ADMIN owners $(cast call "$NESTED_ADMIN" "getOwners()(address[])" --rpc-url "$LOCAL") (deployer not among them)"
guard "NEW_ADMIN owned by a Safe the deployer owns" "an owner of the NEW_ADMIN Safe is owned by the deployer" \
    "NEW_ADMIN=$NESTED_ADMIN" "NEW_ADMIN_OWNER=$OWNER_STANDIN"

# An owner that is a contract but not a Safe cannot be inspected, so it must be refused rather than assumed safe.
echo "  getOwners() probe on the BioRig proxy: $(cast call "$PROXY" "getOwners()(address[])" --rpc-url "$LOCAL" 2>&1 | head -1)"
UNINSPECTABLE_ADMIN=$(new_safe "$PROXY" $((SALT_NONCE + 2))) || exit 1
guard "NEW_ADMIN owned by a contract that cannot be inspected" "cannot inspect" \
    "NEW_ADMIN=$UNINSPECTABLE_ADMIN" "NEW_ADMIN_OWNER=$OWNER_STANDIN"

echo "  ALLOW_UNINSPECTED_OWNER override, positive control (a dry run, nothing broadcast):"
OUT=$(env NEW_ADMIN="$UNINSPECTABLE_ADMIN" NEW_ADMIN_OWNER="$OWNER_STANDIN" ALLOW_UNINSPECTED_OWNER=true \
    forge script --rpc-url "$LOCAL" script/HardenMainnetAdmin.s.sol:HardenMainnetAdmin 2>&1); RC=$?
if [ $RC -eq 0 ] && printf '%s' "$OUT" | grep -qF "WARNING: uninspected contract owner accepted"; then
    echo "  PASS  override accepted an uninspected contract owner, and said so"
else
    echo "  FAIL  override path exit=$RC (wanted exit 0 and the warning line)"
    printf '%s' "$OUT" | grep -E "script failed|Error" | head -2
    FAILED=$((FAILED + 1))
fi

# Depth bound: a chain of contract owners deeper than the walk allows must be refused, not walked. Built bottom-up
# from an EOA, each level owned by the one below it.
CHAIN=$OWNER_STANDIN
for _i in 4 3 2 1; do CHAIN=$(new_safe "$CHAIN" $((SALT_NONCE + 10 - _i))) || exit 1; done
DEEP_ADMIN=$(new_safe "$CHAIN" $((SALT_NONCE + 20))) || exit 1
guard "NEW_ADMIN owner chain deeper than the walk" "nested deeper than this script verifies" \
    "NEW_ADMIN=$DEEP_ADMIN" "NEW_ADMIN_OWNER=$OWNER_STANDIN"
guard "VERIFIER_ADDRESS is NEW_ADMIN" "VERIFIER_ADDRESS is NEW_ADMIN" \
    "NEW_ADMIN=$SAFE" "NEW_ADMIN_OWNER=$OWNER_STANDIN" "VERIFIER_ADDRESS=$SAFE"
guard "NEW_ADMIN is the deployer" "NEW_ADMIN is the deployer" \
    "NEW_ADMIN=$DEPLOYER" "NEW_ADMIN_OWNER=$OWNER_STANDIN"
guard "VERIFIER_ADDRESS is the zero address" "VERIFIER_ADDRESS is the zero address" \
    "NEW_ADMIN=$SAFE" "NEW_ADMIN_OWNER=$OWNER_STANDIN" "VERIFIER_ADDRESS=$ZERO"
guard "wrong CHAIN_ID" "" "CHAIN_ID=11142220"
guard "PROXY_ADDRESS without code" "" "PROXY_ADDRESS=$ZERO"
echo "  preflight guard failures: $FAILED"

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
echo "### end state, mode $MODE"
check "deployer DEFAULT_ADMIN_ROLE" "$(rol "$ADMIN_ROLE" "$DEPLOYER")" false
check "deployer UPGRADER_ROLE" "$(rol "$UPGRADER_ROLE" "$DEPLOYER")" false
check "Safe DEFAULT_ADMIN_ROLE" "$(rol "$ADMIN_ROLE" "$SAFE")" true
check "Safe UPGRADER_ROLE" "$(rol "$UPGRADER_ROLE" "$SAFE")" true
check "Safe VERIFIER_ROLE" "$(rol "$VERIFIER_ROLE" "$SAFE")" false
if [ "$MODE" = B ]; then
    check "deployer VERIFIER_ROLE (kept)" "$(rol "$VERIFIER_ROLE" "$DEPLOYER")" true
else
    check "deployer VERIFIER_ROLE" "$(rol "$VERIFIER_ROLE" "$DEPLOYER")" false
    check "verifier VERIFIER_ROLE" "$(rol "$VERIFIER_ROLE" "$VERIFIER_ADDRESS")" true
    check "verifier DEFAULT_ADMIN_ROLE" "$(rol "$ADMIN_ROLE" "$VERIFIER_ADDRESS")" false
fi
check "VERIFIER_ROLE admin" "$(cast call "$PROXY" "getRoleAdmin(bytes32)(bytes32)" "$VERIFIER_ROLE" --rpc-url "$LOCAL" | tr -d '[:space:]')" "$ADMIN_ROLE"

echo
echo "### post-handover behaviour on the fork (mode $MODE)"
PLANTER=0x$(cast keccak "biorig-handover-check-planter" | cut -c27-66)
MINT="mintTree(address,bytes32,uint96,uint96)"
NULLIFIER="$(cast keccak plot-fork-1)"
if [ "$MODE" = B ]; then
    # The point of mode B: minting still works from the deployer key, admin and upgrade do not.
    send_exit "deployer mint" "$PRIVATE_KEY" zero "$MINT" "$PLANTER" "$NULLIFIER" 10 20
elif [ "$VERIFIER_ADDRESS" = "$FORK_VERIFIER" ]; then
    send_exit "deployer mint" "$PRIVATE_KEY" nonzero "$MINT" "$PLANTER" "$NULLIFIER" 10 20
    send_exit "verifier mint" "$VERIFIER_KEY" zero "$MINT" "$PLANTER" "$NULLIFIER" 10 20
else
    echo "  SKIP  mints: VERIFIER_ADDRESS is neither the deployer nor a fork key held here"
fi
# Pause last: a successful pause would block every mint check above.
send_exit "deployer pause" "$PRIVATE_KEY" nonzero pause
if [ "$MODE" = B ] || [ "$VERIFIER_ADDRESS" = "$FORK_VERIFIER" ]; then
    TBA=$(cast call "$PROXY" "getTreeStats(uint256)((uint96,uint96,uint64,address,bool,bytes32))" 1 --rpc-url "$LOCAL" | tr -d '() ' | cut -d, -f4)
    echo "  TBA $TBA token() = $(cast call "$TBA" "token()(uint256,address,uint256)" --rpc-url "$LOCAL" | tr ' ' ' ')"
fi

echo
echo "### second handover run (must be refused: nothing left to hand over)"
SECOND=$(forge script --rpc-url "$LOCAL" script/HardenMainnetAdmin.s.sol:HardenMainnetAdmin 2>&1); SRC=$?
printf '%s' "$SECOND" | grep -m1 -oE 'script failed: .*' | cut -c1-140
if [ $SRC -ne 0 ]; then echo "  PASS  refused (exit $SRC)"; else echo "  FAIL  accepted"; FAILED=$((FAILED + 1)); fi

echo
if [ "$FAILED" -eq 0 ]; then echo "REHEARSAL PASSED: mode $MODE, 0 failures"; else echo "REHEARSAL FAILED: $FAILED check(s)"; fi
exit $FAILED
