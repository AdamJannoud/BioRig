"""Set the pre-operation state of the 1 October 2026 Celo mainnet operations on an anvil fork of the TIP.

    .venv/bin/python tools/fork_reconstruct.py --rpc-url http://127.0.0.1:8549            # write, then assert
    .venv/bin/python tools/fork_reconstruct.py --rpc-url http://127.0.0.1:8549 --dry-run  # print the writes only
    .venv/bin/python tools/fork_reconstruct.py --rpc-url http://127.0.0.1:8549 --json     # machine-readable report

Why: the fork rehearsals (script/safe-owner-swap-fork-check.sh, script/handover-fork-check.sh) rest on the state
before the Safe owner swap and the role handover executed. Forking block 78991456 needs historical state, which the
public Celo RPCs do not serve. Tip state they do serve, and the operations are on record, so this tool forks nothing
itself: it takes a tip fork and inverts the executed transactions on it.

  1. The executed tx hashes are read from the committed broadcast records (MANIFEST), never transcribed.
  2. Each receipt is fetched and its logs inverted, newest first: RemovedOwner(o) puts o back, AddedOwner(o) drops
     it, each ExecutionSuccess/ExecutionFailure on the Safe takes one off its nonce, RoleGranted(r, a) revokes and
     RoleRevoked(r, a) grants. A ChangedThreshold log leaves the old threshold unrecoverable from the log alone, so it
     is a reconstruction gap, not a guess.
  3. Tip values are read with eth_call / eth_getStorageAt; the writes go in with anvil_setStorageAt: the Safe's owner
     linked list (the removed owner's own entry zeroed, or isOwner() would still say true), ownerCount, threshold,
     nonce, and each touched (role, account) member flag.
  4. The whole snapshot is read back through the contracts' own getters and must equal both the derived values and
     TARGET, the state at block 78991456 that both rehearsals passed against on 1 October 2026.

What this does NOT do: read historical state. The fork is the tip with the pre-op snapshot set on it, so the
operations are proven against a state matching that snapshot, not against the exact contents of block 78991456.
Unrelated later activity (the pilot mint at block 78992489) is still there. FORK_MODE=pin in the harnesses remains
the archival-exact mode.

Exit status: 0 snapshot written (or, with --dry-run, derived) and asserted; 2 an environment or reconstruction gap
(record missing, RPC failure, a log that cannot be inverted, a read-back mismatch), reported as ONE "FATAL:" line.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

try:
    from eth_abi import decode, encode
    from eth_utils import keccak, to_checksum_address
except ImportError as exc:  # the harnesses check this first; a direct run gets the same one-line answer
    print(f"FATAL: {exc.name} is not installed; pip install -r tools/requirements.txt (into .venv)")
    sys.exit(2)

ROOT = Path(__file__).resolve().parent.parent

PROXY = "0x04Db169dDF8AbB80943161C01B2a71DC40384E64"
SAFE = "0x3B36b3446fCB0729B0046520156933E56352D551"
DEPLOYER = "0x1DB0084Db70bF8D0E06c1785D693Fc6a95317890"
NEW_SAFE_OWNER = "0xD314e37FD8538fe66231EE670B74C9428d03feEa"
SENTINEL = "0x0000000000000000000000000000000000000001"

# Executed transactions, as committed by forge. The hashes are read out of these at run time.
MANIFEST = (
    "broadcast/SafeOwnerSwap.s.sol/42220/run-latest.json",
    "broadcast/HardenMainnetAdmin.s.sol/42220/run-latest.json",
)

# Safe storage (verified against the live Safe): owners mapping, ownerCount, threshold, nonce.
SAFE_OWNERS_SLOT, SAFE_OWNER_COUNT_SLOT, SAFE_THRESHOLD_SLOT, SAFE_NONCE_SLOT = 2, 3, 4, 5

# OpenZeppelin v5 keeps _roles in ERC-7201 namespaced storage; the base is read from the vendored source, because a
# hand-derived value of exactly this constant was wrong once.
OZ_ACCESS_CONTROL = ROOT / "lib/openzeppelin-contracts-upgradeable/contracts/access/AccessControlUpgradeable.sol"

ROLES = {
    "DEFAULT_ADMIN_ROLE": b"\x00" * 32,
    "UPGRADER_ROLE": keccak(text="UPGRADER_ROLE"),
    "VERIFIER_ROLE": keccak(text="VERIFIER_ROLE"),
}
ROLE_NAMES = {v: k for k, v in ROLES.items()}
ACCOUNTS = {"deployer": DEPLOYER, "Safe": SAFE, "new Safe owner": NEW_SAFE_OWNER}

TOPIC = {
    "AddedOwner": "0x9465fa0c962cc76958e6373a993326400c1c94f8be2fe3a952adfa7f60b2ea26",
    "RemovedOwner": "0xf8d49fc529812e9a7c5c50e69c20f0dccc0db8fa95c98bc58cc9a4f1c1299eaf",
    "ChangedThreshold": "0x610f7ff2b304ae8903c3de74c60c6ab1f7d6226b3f52c5161905bb5ad4039c93",
    "ExecutionSuccess": "0x442e715f626346e8c54381002da614f62bee8d27386535b2521ec8540898556e",
    # A failed Safe transaction still spends its nonce, so it inverts exactly like a success.
    "ExecutionFailure": "0x" + keccak(text="ExecutionFailure(bytes32,uint256)").hex(),
    "RoleGranted": "0x2f8788117e7eff1d82e926ec794901d17c78024a50270940304540a733656f0d",
    "RoleRevoked": "0xf6391f5c32d9c69d2a47ea670b442974b53935d1edc7fd64eb21e047a839171b",
    # SafeL2's informational event: carries the call, changes no state.
    "SafeMultiSigTransaction": "0x66753cd2356569ee081232e3be8909b950e0a76c1f8460c3a5e3c2be32b11bed",
}
TOPIC_NAMES = {v: k for k, v in TOPIC.items()}

# Mainnet at block 78991456, the state both rehearsals were pinned to and passed against on 1 October 2026.
TARGET = {
    "owners": [DEPLOYER],
    "threshold": 1,
    "nonce": 0,
    "roles": {
        (role, account): account == DEPLOYER for role in ROLES.values() for account in ACCOUNTS.values()
    },
}


class Gap(Exception):
    """The pre-op state cannot be set or confirmed; the message is the one FATAL line."""


# ---------------------------------------------------------------- pure derivations (tested in test_fork_reconstruct)

def roles_base_slot(source: Path = OZ_ACCESS_CONTROL) -> int:
    """The ERC-7201 base of AccessControlUpgradeable's storage, read off the vendored OpenZeppelin source."""
    try:
        text = source.read_text()
    except OSError as exc:
        raise Gap(f"cannot read the AccessControl storage location from {source}: {exc}") from exc
    m = re.search(r"AccessControlStorageLocation\s*=\s*(0x[0-9a-fA-F]{64})\s*;", text)
    if not m:
        raise Gap(f"no AccessControlStorageLocation constant in {source}")
    return int(m.group(1), 16)


def mapping_slot(key_type: str, key, slot: int) -> int:
    """keccak256(abi.encode(key, slot)): the storage key of mapping[key] for a mapping at `slot`."""
    return int.from_bytes(keccak(encode([key_type, "uint256"], [key, slot])), "big")


def role_member_slot(role: bytes, account: str, base: int) -> int:
    """_roles[role].hasRole[account]: RoleData's hasRole mapping sits at offset 0 of _roles[role]."""
    return mapping_slot("address", account, mapping_slot("bytes32", role, base))


def owner_slot(owner: str) -> int:
    return mapping_slot("address", owner, SAFE_OWNERS_SLOT)


def owner_links(owners: list[str], removed: list[str] = ()) -> dict[str, str]:
    """The Safe's owners mapping for `owners` in order: SENTINEL -> first -> ... -> last -> SENTINEL. Each address in
    `removed` maps to zero, because isOwner(a) is owners[a] != 0 and a stale entry would keep a dropped owner."""
    if not owners:
        raise Gap("a Safe with no owners cannot be reconstructed")
    chain = [SENTINEL, *owners, SENTINEL]
    links = {chain[i]: chain[i + 1] for i in range(len(chain) - 1)}
    for a in removed:
        if a not in links:
            links[a] = "0x" + "00" * 20
    return links


@dataclass
class Inversion:
    owners: list[str]
    nonce: int
    threshold: int
    roles: dict[tuple[bytes, str], bool]
    removed_owners: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def _addr(topic: str) -> str:
    return to_checksum_address("0x" + topic[-40:])


def _same(a: str, b: str) -> bool:
    return a.lower() == b.lower()


def invert(logs: list[dict], tip_owners: list[str], tip_nonce: int, tip_threshold: int,
           tip_roles: dict[tuple[bytes, str], bool]) -> Inversion:
    """Undo `logs` (receipt logs, any order) against the tip values. Logs are replayed newest first, so a pair of
    events on the same key inside the batch inverts to the state before the first of them."""
    ordered = sorted(logs, key=lambda l: (int(l["blockNumber"], 16), int(l["transactionIndex"], 16),
                                          int(l["logIndex"], 16)), reverse=True)
    owners = [to_checksum_address(o) for o in tip_owners]
    nonce, threshold = tip_nonce, tip_threshold
    roles = dict(tip_roles)
    removed: list[str] = []
    skipped: list[str] = []
    swap_slot: dict[str, int] = {}  # tx hash -> position of the owner AddedOwner dropped, for an in-place swapOwner
    for log in ordered:
        topics = [t.lower() for t in log["topics"]]
        name = TOPIC_NAMES.get(topics[0]) if topics else None
        where = f"{log['transactionHash']} log {int(log['logIndex'], 16)}"
        on_safe, on_proxy = _same(log["address"], SAFE), _same(log["address"], PROXY)
        if name == "SafeMultiSigTransaction" and on_safe:
            continue
        if name == "ChangedThreshold" and on_safe:
            raise Gap(f"reconstruction gap: ChangedThreshold in {where} - the pre-op threshold is not in the log, "
                      "and this tool does not guess it")
        if name == "AddedOwner" and on_safe:
            o = _addr(log["data"] if len(topics) == 1 else topics[1])
            if o not in owners:
                raise Gap(f"reconstruction gap: AddedOwner({o}) in {where}, but {o} is not an owner at the tip "
                          "(already reconstructed, or the Safe moved on)")
            swap_slot[log["transactionHash"]] = owners.index(o)
            owners.remove(o)
            removed.append(o)
        elif name == "RemovedOwner" and on_safe:
            o = _addr(log["data"] if len(topics) == 1 else topics[1])
            if o in owners:
                raise Gap(f"reconstruction gap: RemovedOwner({o}) in {where}, but {o} is still an owner at the tip")
            owners.insert(swap_slot.pop(log["transactionHash"], 0), o)
            if o in removed:
                removed.remove(o)
        elif name in ("ExecutionSuccess", "ExecutionFailure") and on_safe:
            nonce -= 1
            if nonce < 0:
                raise Gap(f"reconstruction gap: {name} in {where} takes the Safe nonce below zero")
        elif name in ("RoleGranted", "RoleRevoked") and on_proxy:
            role, account = bytes.fromhex(topics[1][2:]), _addr(topics[2])
            roles[(role, account)] = name == "RoleRevoked"
        else:
            skipped.append(f"{where} on {log['address']}: topic {topics[0] if topics else '(none)'}")
    return Inversion(owners, nonce, threshold, roles, removed, skipped)


def read_manifest(root: Path = ROOT) -> list[str]:
    """Every executed tx hash, in record order, from the committed broadcast records."""
    hashes: list[str] = []
    for rel in MANIFEST:
        path = root / rel
        try:
            txs = json.loads(path.read_text()).get("transactions") or []
        except (OSError, ValueError) as exc:
            raise Gap(f"broadcast record {rel} is missing or unreadable: {exc}") from exc
        if not txs:
            raise Gap(f"broadcast record {rel} holds no transactions")
        hashes += [t["hash"].lower() for t in txs]
    return hashes


# ---------------------------------------------------------------- chain I/O

class Rpc:
    """A bare JSON-RPC client: the tool needs eth_call, eth_getStorageAt, a receipt and anvil_setStorageAt."""

    def __init__(self, url: str):
        self.url = url
        self._id = 0

    def __call__(self, method: str, *params):
        self._id += 1
        body = json.dumps({"jsonrpc": "2.0", "id": self._id, "method": method, "params": list(params)}).encode()
        req = urllib.request.Request(self.url, body, {"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                reply = json.loads(resp.read())
        except (OSError, ValueError) as exc:
            raise Gap(f"RPC {method} to {self.url} failed: {exc}") from exc
        if "error" in reply:
            raise Gap(f"RPC {method} to {self.url} returned an error: {reply['error']}")
        return reply.get("result")


def _call(rpc, to: str, sig: str, types: list[str], args: list, out: list[str]):
    data = keccak(text=sig)[:4] + encode(types, args)
    raw = rpc("eth_call", {"to": to, "data": "0x" + data.hex()}, "latest")
    return decode(out, bytes.fromhex(raw[2:]))


def read_safe(rpc) -> tuple[list[str], int, int]:
    (owners,) = _call(rpc, SAFE, "getOwners()", [], [], ["address[]"])
    (threshold,) = _call(rpc, SAFE, "getThreshold()", [], [], ["uint256"])
    (nonce,) = _call(rpc, SAFE, "nonce()", [], [], ["uint256"])
    return [to_checksum_address(o) for o in owners], threshold, nonce


def read_role(rpc, role: bytes, account: str) -> bool:
    return _call(rpc, PROXY, "hasRole(bytes32,address)", ["bytes32", "address"], [role, account], ["bool"])[0]


def storage(rpc, address: str, slot: int) -> int:
    return int(rpc("eth_getStorageAt", address, hex(slot), "latest"), 16)


def fetch_logs(rpc, hashes: list[str]) -> list[dict]:
    logs: list[dict] = []
    for h in hashes:
        receipt = rpc("eth_getTransactionReceipt", h)
        if not receipt:
            raise Gap(f"no receipt for executed tx {h} via the fork's upstream")
        if int(receipt.get("status", "0x0"), 16) != 1:
            raise Gap(f"executed tx {h} has receipt status {receipt.get('status')}; nothing to invert")
        logs += receipt["logs"]
    return logs


# ---------------------------------------------------------------- reconstruction

def _word(value: int) -> str:
    return "0x" + value.to_bytes(32, "big").hex()


def _label(role: bytes, account: str) -> str:
    who = next((k for k, v in ACCOUNTS.items() if _same(v, account)), account)
    return f"{ROLE_NAMES.get(role, '0x' + role.hex())} x {who}"


def plan(rpc, root: Path = ROOT) -> dict:
    """Derive the pre-op snapshot and the storage writes that set it, from the record, the receipts and the tip."""
    hashes = read_manifest(root)
    base = roles_base_slot(root / OZ_ACCESS_CONTROL.relative_to(ROOT))
    logs = fetch_logs(rpc, hashes)

    tip_owners, tip_threshold, tip_nonce = read_safe(rpc)
    tip_count = storage(rpc, SAFE, SAFE_OWNER_COUNT_SLOT)
    if tip_count != len(tip_owners):
        raise Gap(f"Safe ownerCount slot holds {tip_count} but getOwners() lists {len(tip_owners)}: the storage "
                  "layout is not the one this tool writes")
    pairs = {(r, a) for r in ROLES.values() for a in ACCOUNTS.values()}
    for log in logs:
        t = [x.lower() for x in log["topics"]]
        if _same(log["address"], PROXY) and t and TOPIC_NAMES.get(t[0]) in ("RoleGranted", "RoleRevoked"):
            pairs.add((bytes.fromhex(t[1][2:]), _addr(t[2])))
    tip_roles = {p: read_role(rpc, *p) for p in pairs}
    for (role, account), held in tip_roles.items():  # the layout this tool writes must be the one the getter reads
        if bool(storage(rpc, PROXY, role_member_slot(role, account, base))) != held:
            raise Gap(f"hasRole({_label(role, account)}) disagrees with its derived storage key: wrong ERC-7201 base")

    inv = invert(logs, tip_owners, tip_nonce, tip_threshold, tip_roles)
    touched = {(bytes.fromhex(t[1][2:]), _addr(t[2])) for log in logs
               for t in [[x.lower() for x in log["topics"]]]
               if _same(log["address"], PROXY) and t and TOPIC_NAMES.get(t[0]) in ("RoleGranted", "RoleRevoked")}

    writes = []  # (address, slot, value, label)
    dropped = [o for o in tip_owners if o not in inv.owners]
    for owner, nxt in owner_links(inv.owners, dropped).items():
        writes.append((SAFE, owner_slot(owner), int(nxt, 16), f"Safe owners[{owner}] = {to_checksum_address(nxt)}"))
    writes.append((SAFE, SAFE_OWNER_COUNT_SLOT, len(inv.owners), f"Safe ownerCount = {len(inv.owners)}"))
    writes.append((SAFE, SAFE_THRESHOLD_SLOT, inv.threshold, f"Safe threshold = {inv.threshold}"))
    writes.append((SAFE, SAFE_NONCE_SLOT, inv.nonce, f"Safe nonce = {inv.nonce} (tip {tip_nonce})"))
    for role, account in sorted(touched):
        held = inv.roles[(role, account)]
        writes.append((PROXY, role_member_slot(role, account, base), int(held),
                       f"proxy hasRole[{_label(role, account)}] = {str(held).lower()}"))
    return {"hashes": hashes, "inversion": inv, "writes": writes, "base": base}


def check_target(inv: Inversion) -> None:
    """The derived snapshot must be the 78991456 state the rehearsals passed against: the two-sided confirmation."""
    if inv.owners != TARGET["owners"]:
        raise Gap(f"derived Safe owners {inv.owners} are not the pre-op owners {TARGET['owners']}")
    for key in ("threshold", "nonce"):
        if getattr(inv, key) != TARGET[key]:
            raise Gap(f"derived Safe {key} {getattr(inv, key)} is not the pre-op {key} {TARGET[key]}")
    for pair, want in TARGET["roles"].items():
        if inv.roles[pair] != want:
            raise Gap(f"derived hasRole({_label(*pair)}) = {inv.roles[pair]}, pre-op it was {want}")


def apply_and_verify(rpc, p: dict) -> None:
    for address, slot, value, _ in p["writes"]:
        rpc("anvil_setStorageAt", address, _word(slot), _word(value))
    inv = p["inversion"]
    owners, threshold, nonce = read_safe(rpc)
    if owners != inv.owners:
        raise Gap(f"after the writes getOwners() = {owners}, wanted {inv.owners}")
    if (threshold, nonce) != (inv.threshold, inv.nonce):
        raise Gap(f"after the writes threshold/nonce = {threshold}/{nonce}, wanted {inv.threshold}/{inv.nonce}")
    for o in inv.removed_owners:
        (still,) = _call(rpc, SAFE, "isOwner(address)", ["address"], [o], ["bool"])
        if still:
            raise Gap(f"after the writes isOwner({o}) is still true: its owners entry was not zeroed")
    for pair, want in inv.roles.items():
        got = read_role(rpc, *pair)
        if got != want:
            raise Gap(f"after the writes hasRole({_label(*pair)}) = {got}, wanted {want}")


def report(p: dict, dry_run: bool, as_json: bool) -> None:
    inv = p["inversion"]
    if as_json:
        print(json.dumps({
            "dry_run": dry_run,
            "transactions": p["hashes"],
            "roles_base_slot": _word(p["base"]),
            "writes": [{"address": a, "slot": _word(s), "value": _word(v), "label": l} for a, s, v, l in p["writes"]],
            "snapshot": {"owners": inv.owners, "threshold": inv.threshold, "nonce": inv.nonce,
                         "roles": {_label(*k): v for k, v in sorted(inv.roles.items())}},
            "skipped_logs": inv.skipped,
        }, indent=1))
        return
    print(f"reconstruct: {len(p['hashes'])} executed txs from the broadcast records, inverted newest first")
    for h in p["hashes"]:
        print(f"  tx {h}")
    for s in inv.skipped:
        print(f"  skipped unrecognised log {s}")
    print(f"  AccessControl ERC-7201 base {_word(p['base'])} (read from the OpenZeppelin source)")
    print("writes" + (" (dry run, nothing written)" if dry_run else " (anvil_setStorageAt)") + ":")
    for address, slot, value, label in p["writes"]:
        print(f"  {label:<58} {address} [{_word(slot)}] <- {hex(value)}")
    print("pre-op snapshot" + ("" if dry_run else ", read back from the fork") + ":")
    print(f"  Safe {SAFE} owners {inv.owners} threshold {inv.threshold} nonce {inv.nonce}")
    for pair, held in sorted(inv.roles.items(), key=lambda kv: _label(*kv[0])):
        print(f"  hasRole {_label(*pair):<36} {str(held).lower()}")


def run(rpc, dry_run: bool = False, as_json: bool = False, root: Path = ROOT) -> int:
    try:
        p = plan(rpc, root)
        check_target(p["inversion"])
        if not dry_run:
            apply_and_verify(rpc, p)
    except Gap as gap:
        print(f"FATAL: {gap}")
        return 2
    report(p, dry_run, as_json)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--rpc-url", required=True, help="the anvil fork of the Celo mainnet tip")
    ap.add_argument("--dry-run", action="store_true", help="derive and print the writes; write nothing")
    ap.add_argument("--json", action="store_true", help="print the report as JSON")
    args = ap.parse_args(argv)
    return run(Rpc(args.rpc_url), args.dry_run, args.json)


if __name__ == "__main__":
    sys.exit(main())
