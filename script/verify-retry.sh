#!/usr/bin/env bash
# Verifies the two contracts Blockscout still needs, retrying through its rate limiter.
set -uo pipefail
cd /workspace/bio-rig
set -a; . ./.env; set +a

RPC=$RPC_URL
REG=0x000000006551c19487814612e58FE06813775758
PROXY=0x21ab8B36177F65ce69e04E281E4aFf3Db6b5f7E6
IMPL=0x4c998C6553C78bb9d5A67Aac6fBC526d64DBa3a4
API=https://celo-sepolia.blockscout.com/api/v2/addresses
mkdir -p evidence
LOG=evidence/verify-retry.log
: > "$LOG"

echo "=== registry bytecode: on-chain vs this repo's compile ===" | tee -a "$LOG"
cast code "$REG" --rpc-url "$RPC" | sed 's/^0x//' > /tmp/onchain.hex
forge inspect src/vendor/ERC6551Registry.sol:ERC6551Registry deployedBytecode | sed 's/^0x//' > /tmp/compiled.hex
python3 - <<'PY' 2>&1 | tee -a "$LOG"
def strip_meta(h):
    b = bytes.fromhex(h.strip())
    n = int.from_bytes(b[-2:], 'big')
    if 0 < n <= 200:
        return b[:len(b) - n - 2], b[len(b) - n - 2:]
    return b, b''

onchain, om = strip_meta(open('/tmp/onchain.hex').read())
compiled, cm = strip_meta(open('/tmp/compiled.hex').read())
print(f"on-chain runtime : {len(onchain) + len(om)} bytes (executable {len(onchain)}, metadata {len(om)})")
print(f"compiled runtime : {len(compiled) + len(cm)} bytes (executable {len(compiled)}, metadata {len(cm)})")
print(f"executable code identical : {onchain == compiled}")
print(f"metadata identical        : {om == cm}")
PY

is_verified() {
  curl -s "$API/$1" | jq -r '.is_verified // false'
}

attempt() {
  local addr=$1 fqn=$2 label=$3; shift 3
  for i in 1 2 3 4 5 6; do
    echo "" | tee -a "$LOG"
    echo "--- $label: attempt $i ---" | tee -a "$LOG"
    forge verify-contract "$addr" "$fqn" --verifier blockscout --verifier-url "$VERIFIER_URL" \
      --chain 11142220 "$@" 2>&1 | grep -v '^Constructor args' | tail -8 | tee -a "$LOG"
    sleep 5
    local v; v=$(is_verified "$addr")
    echo "blockscout is_verified=$v" | tee -a "$LOG"
    [ "$v" = "true" ] && { echo "RESULT $label: VERIFIED" | tee -a "$LOG"; return 0; }
    sleep 45
  done
  echo "RESULT $label: NOT VERIFIED after 6 attempts" | tee -a "$LOG"
  return 1
}

INIT=$(cast calldata "initialize(address,address,address,uint256,address,address)" \
  0xb5aB2054b43040593805Cf662A938eFE924F2778 \
  0x000000006551c19487814612e58FE06813775758 \
  0x3d8a53dB1bBcab6D47097B25080527e5560C5165 \
  11142220 \
  0xb5aB2054b43040593805Cf662A938eFE924F2778 \
  0x0000000000000000000000000000000000000000)
ARGS=$(cast abi-encode "f(address,bytes)" "$IMPL" "$INIT")

attempt "$PROXY" "lib/openzeppelin-contracts/contracts/proxy/ERC1967/ERC1967Proxy.sol:ERC1967Proxy" "proxy" --constructor-args "$ARGS"
attempt "$REG" "src/vendor/ERC6551Registry.sol:ERC6551Registry" "canonical-registry"

echo "" | tee -a "$LOG"
echo "=== final on-chain verification status ===" | tee -a "$LOG"
for a in "$REG" "$PROXY" "$IMPL" 0x3d8a53dB1bBcab6D47097B25080527e5560C5165; do
  printf "%s  is_verified=%s\n" "$a" "$(is_verified "$a")" | tee -a "$LOG"
  sleep 2
done
