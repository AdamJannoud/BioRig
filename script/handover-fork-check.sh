#!/usr/bin/env bash
# Rehearse the Celo mainnet role handover against a fork of the chain, using the live proxy and the real deployer key
# as the local sender. Nothing is broadcast: anvil is forked, the handover runs on the fork, anvil stops. Only the
# fork's own stand-ins (VERIFIER_ADDRESS, NEW_ADMIN Safe) are anvil accounts.
#
# This no longer rehearses something pending: mode B EXECUTED on mainnet on 1 October 2026 (four transactions, blocks
# 78991473-78991482), so the tip holds a proxy the deployer can no longer hand over (it has neither admin nor upgrader)
# and a Safe owned by 0xD314e37FD8538fe66231EE670B74C9428d03feEa. The rehearsal needs the state BEFORE that, and
# FORK_MODE says how it gets it:
#
#   reconstruct (default)  fork the TIP, then tools/fork_reconstruct.py sets the pre-op snapshot on it by inverting
#                          the executed transactions (hashes read from broadcast/*/42220/run-latest.json) and asserts
#                          it by read-back. No archive endpoint needed. It does NOT read historical state: the
#                          handover is proven against a state matching the snapshot at block 78991456, not that block's
#                          exact contents, and unrelated later activity at the tip is still present (the pilot mint at
#                          block 78992489 is not rewound). The run says so in its output too.
#   pin                    fork at FORK_BLOCK (default 78991456, the block the handover was rehearsed from and run at):
#                          the archival-exact mode. FORK_URL must be an ARCHIVE endpoint: anvil fetches chain state at
#                          that block, and the public Celo RPCs serve historical state only intermittently (measured
#                          2 October 2026, see the gate below). Without one this script exits 2 before asserting.
#   raw                    fork the tip with no reconstruction, where the checks below FAIL by design (exit 1): the
#                          handover has already run.
#
# FORK_MODE unset keeps the old FORK_BLOCK contract: FORK_BLOCK unset -> reconstruct, a number -> pin, tip -> raw.
# Exit: 0 green, 1 a real check failed, 2 an environment gap (no fork, no reconstruction) before anything is asserted.
set -uo pipefail
cd "$(dirname "$0")/.."
export HOME=/root
CHAIN_ID=42220
# An exported FORK_URL wins, so a rehearsal at a past block can be pointed at an archive endpoint; otherwise the
# chain registry. The old form assigned unconditionally, which made the archive instruction below impossible to follow.
FORK_URL=${FORK_URL:-$(python3 -m dashboard.config get rpc_url --chain-id 42220)}
PROXY=0x04Db169dDF8AbB80943161C01B2a71DC40384E64
PORT=${FORK_PORT:-8549}
LOCAL="http://127.0.0.1:$PORT"
KEY=${KEY_FILE:-/tmp/biorig-audit/deployer.key}

# FORK_MODE picks how the fork gets its pre-operation state; see the header. Unset, it follows FORK_BLOCK as before:
# FORK_BLOCK unset -> reconstruct, a block number -> pin, tip/latest/empty -> raw.
if [ -z "${FORK_MODE:-}" ]; then
    if [ -z "${FORK_BLOCK+set}" ]; then FORK_MODE=reconstruct
    else case "$FORK_BLOCK" in "" | tip | latest) FORK_MODE=raw ;; *) FORK_MODE=pin ;; esac
    fi
fi
case "$FORK_MODE" in
    pin)
        FORK_BLOCK=${FORK_BLOCK:-78991456}   # the block the handover was rehearsed from and run at (txs 78991473-78991482)
        case "$FORK_BLOCK" in *[!0-9]*)
            echo "FATAL: FORK_MODE=pin needs a block number, not FORK_BLOCK=$FORK_BLOCK"; exit 2 ;; esac
        FORK_LABEL="block $FORK_BLOCK"; FORK_ARGS=(--fork-block-number "$FORK_BLOCK") ;;
    raw)   # an unpinned anvil forks the tip; anvil rejects a literal "latest" as a block number
        FORK_BLOCK=tip; FORK_LABEL="the chain tip"; FORK_ARGS=() ;;
    reconstruct)
        FORK_BLOCK=tip; FORK_LABEL="the chain tip (for reconstruction)"; FORK_ARGS=() ;;
    *) echo "FATAL: FORK_MODE=$FORK_MODE is not one of reconstruct, pin, raw"; exit 2 ;;
esac
if [ "$FORK_MODE" = reconstruct ]; then   # the repo's interpreter convention, then whatever python3 is on PATH
    PY=.venv/bin/python; [ -x "$PY" ] || PY=python3
    if ! "$PY" -c 'import eth_utils, eth_abi' >/dev/null 2>&1; then
        echo "FATAL: $PY cannot import eth_utils/eth_abi; install tools/requirements.txt (pip install -r tools/requirements.txt)"
        echo "       Nothing was asserted: this is an environment gap, not a mismatch in the on-chain facts."
        exit 2
    fi
fi

anvil --fork-url "$FORK_URL" --port "$PORT" "${FORK_ARGS[@]}" --silent &
ANVIL_PID=$!
trap 'kill $ANVIL_PID 2>/dev/null; wait $ANVIL_PID 2>/dev/null; echo "[anvil stopped]"' EXIT
# Anvil builds a pinned fork's genesis from ~28 consecutive historical-state reads at $FORK_BLOCK. The public Celo RPCs
# answer those only intermittently (forno about half the time, 1rpc/blockpi/thirdweb/onfinality none of the time), so a
# fork at a past block needs an archive endpoint. Fail with that reason here, rather than letting the checks below
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
if [ "$FORK_MODE" = reconstruct ]; then
    echo "### reconstruct: pre-op snapshot set on a tip fork from the executed transactions"
    RECON=$("$PY" tools/fork_reconstruct.py --rpc-url "$LOCAL" 2>&1); RECON_RC=$?
    if [ $RECON_RC -ne 0 ]; then
        printf '%s\n' "$RECON" | grep -m1 '^FATAL' \
            || { echo "FATAL: tools/fork_reconstruct.py exited $RECON_RC"; printf '%s\n' "$RECON" | tail -3; }
        echo "       Nothing was asserted: the pre-op state could not be set on the tip fork."
        exit 2
    fi
    printf '%s\n' "$RECON" | sed 's/^/    /'
    echo "    NOTE: this fork is the chain TIP with the pre-op snapshot written into storage, derived by inverting the"
    echo "          executed transactions. No historical state was read: the operations are proven against a state"
    echo "          matching the snapshot at block 78991456, not that block's exact contents, and unrelated later"
    echo "          activity at the tip is still present (the pilot mint at block 78992489 is not rewound)."
    echo "          FORK_MODE=pin is the archival-exact mode."
fi

export FOUNDRY_BROADCAST=cache/handover-fork-check/broadcast
# Both documented forms of the deployer key are accepted here (64 bare hex digits, or 0x + 64 hex): the Forge scripts
# read it through script/PrivateKeyEnv.sol, which takes either. The check below only proves the key derives to the
# deployer.
PRIVATE_KEY=$(cat "$KEY")
export PRIVATE_KEY
export CHAIN_ID PROXY_ADDRESS="$PROXY"
if ! DEPLOYER=$(cast wallet address --private-key "$PRIVATE_KEY" 2>&1); then
    echo "FATAL: $KEY does not hold a usable private key: $DEPLOYER"; exit 1
fi
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
case "$FORK_MODE" in
    reconstruct) echo "  MODE  reconstruct: a tip fork with the pre-handover snapshot set by tools/fork_reconstruct.py, whose own read-back is the gate" ;;
    raw) echo "  SKIP  fork pinned to the pre-handover block (FORK_MODE=raw forks the tip, nothing reconstructed)" ;;
    *) check "fork pinned to the pre-handover block" "$(cast block-number --rpc-url "$LOCAL")" "$FORK_BLOCK" ;;
esac
echo "live proxy $PROXY  code size $(cast codesize "$PROXY" --rpc-url "$LOCAL")"
echo "sender (real deployer key, local only) $DEPLOYER  balance $(cast balance "$DEPLOYER" --rpc-url "$LOCAL")"
echo "### BEFORE, against $([ "$FORK_MODE" = reconstruct ] && echo "the pre-handover snapshot reconstructed at the tip" || echo "the chain at $FORK_LABEL")"
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

# Guard-check mode: prove the mode-B preflight refuses a deployer that does not hold VERIFIER_ROLE, then stop. Always
# mode B, whatever VERIFIER_ADDRESS_IN says.
if [ -n "${GUARD_ONLY:-}" ]; then
    echo
    echo "### guard check: mode B, deployer does not hold VERIFIER_ROLE"
    # The guard under test is the mode-B preflight, so this check runs in mode B whatever VERIFIER_ADDRESS_IN says:
    # in mode A the deployer's VERIFIER_ROLE is never consulted and the handover would rightly go through.
    export VERIFIER_ADDRESS=$DEPLOYER
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
ADAM_SAFE=0x3B36b3446fCB0729B0046520156933E56352D551   # Adam's Celo Safe: real, and in the pre-op state still the deployer's
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
# 1, not the count: a count of 2 would read as the environment-gap exit (2) the gates above reserve.
exit $((FAILED > 0 ? 1 : 0))
