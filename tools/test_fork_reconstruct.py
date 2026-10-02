"""Pure-logic tests for tools/fork_reconstruct.py: no RPC, no fork.

The storage keys and the inversion are what the tip-fork rehearsals stand on, so each is pinned against a value that
did not come from the code under test: the base against the expected constant, the member-flag and owner keys against
`cast index`, the manifest against the five hashes the operations executed as.
"""

from __future__ import annotations

import pytest

from tools import fork_reconstruct as fr

DEPLOYER, NEW_OWNER, SAFE, PROXY = fr.DEPLOYER, fr.NEW_SAFE_OWNER, fr.SAFE, fr.PROXY
A = "0x000000000000000000000000000000000000000A"
B = "0x000000000000000000000000000000000000000b"
ZERO = "0x" + "00" * 20
ADMIN, UPGRADER, VERIFIER = (fr.ROLES[k] for k in ("DEFAULT_ADMIN_ROLE", "UPGRADER_ROLE", "VERIFIER_ROLE"))


def _topic(addr: str) -> str:
    return "0x" + "00" * 12 + addr[2:].lower()


def _log(address, name, *topics, block=1, tx_index=0, log_index=0, tx="0xaa"):
    return {"address": address, "topics": [fr.TOPIC[name], *topics], "data": "0x", "blockNumber": hex(block),
            "transactionIndex": hex(tx_index), "logIndex": hex(log_index), "transactionHash": tx}


def _role_log(name, role, account, block, sender=DEPLOYER):
    return _log(PROXY, name, "0x" + role.hex(), _topic(account), _topic(sender), block=block, tx=hex(block))


def test_erc7201_base_is_read_from_the_openzeppelin_source():
    assert fr.roles_base_slot() == 0x02dd7bc7dec4dceedda775e58dd541e08a116c6c53815c0bd028192f7b626800


def test_role_member_key_matches_cast_index():
    # cast index address <deployer> $(cast index bytes32 $(cast keccak UPGRADER_ROLE) <base>)
    assert fr.role_member_slot(UPGRADER, DEPLOYER, fr.roles_base_slot()) == \
        0x091636ca5faff95488e199d95399b70bc9cafe49eb58d8963ef20064d83c1225
    # cast index address 0xD314e37FD8538fe66231EE670B74C9428d03feEa 2
    assert fr.owner_slot(NEW_OWNER) == 0xef20957692a95bbcb59a27765964bb06ec46237e5a06cdc8d04b17a8d0dea914


@pytest.mark.parametrize("owners", [[A], [A, B], [A, B, DEPLOYER]])
def test_owner_linked_list(owners):
    links = fr.owner_links(owners)
    assert len(links) == len(owners) + 1
    walk, cur = [], links[fr.SENTINEL]
    while cur != fr.SENTINEL:
        walk.append(cur)
        cur = links[cur]
    assert walk == owners


def test_removed_owner_entry_is_zeroed():
    links = fr.owner_links([DEPLOYER], removed=[NEW_OWNER])
    assert links == {fr.SENTINEL: DEPLOYER, DEPLOYER: fr.SENTINEL, NEW_OWNER: ZERO}
    with pytest.raises(fr.Gap):
        fr.owner_links([])


def _swap_logs():
    """The shape of the 1 October swap receipt: RemovedOwner, AddedOwner, SafeMultiSigTransaction, ExecutionSuccess."""
    return [
        _log(SAFE, "SafeMultiSigTransaction", log_index=0),
        _log(SAFE, "RemovedOwner", _topic(DEPLOYER), log_index=1),
        _log(SAFE, "AddedOwner", _topic(NEW_OWNER), log_index=2),
        _log(SAFE, "ExecutionSuccess", "0x" + "11" * 32, log_index=3),
    ]


def test_inverting_the_swap_restores_owners_nonce_threshold():
    inv = fr.invert(_swap_logs(), [NEW_OWNER], tip_nonce=1, tip_threshold=1, tip_roles={})
    assert (inv.owners, inv.nonce, inv.threshold) == ([DEPLOYER], 0, 1)
    assert inv.removed_owners == [NEW_OWNER] and inv.skipped == []


def test_swap_inverts_in_place_among_several_owners():
    inv = fr.invert(_swap_logs(), [A, NEW_OWNER, B], tip_nonce=5, tip_threshold=2, tip_roles={})
    assert (inv.owners, inv.nonce, inv.threshold) == ([A, DEPLOYER, B], 4, 2)


def test_unrecognised_topic_is_reported_not_applied():
    stray = _log(SAFE, "ExecutionSuccess", log_index=9)
    stray["topics"][0] = "0x" + "ee" * 32
    inv = fr.invert(_swap_logs() + [stray], [NEW_OWNER], 1, 1, {})
    assert len(inv.skipped) == 1 and "0x" + "ee" * 32 in inv.skipped[0]


def test_changed_threshold_is_a_gap_not_a_guess(capsys, monkeypatch):
    logs = _swap_logs() + [_log(SAFE, "ChangedThreshold", log_index=4)]
    with pytest.raises(fr.Gap, match="ChangedThreshold"):
        fr.invert(logs, [NEW_OWNER], 1, 1, {})
    # and through the CLI path: exit 2, one FATAL line, no writes reported
    monkeypatch.setattr(fr, "read_manifest", lambda root=fr.ROOT: ["0xaa"])
    monkeypatch.setattr(fr, "fetch_logs", lambda rpc, hashes: logs)
    monkeypatch.setattr(fr, "read_safe", lambda rpc: ([NEW_OWNER], 1, 1))
    monkeypatch.setattr(fr, "storage", lambda rpc, address, slot: 1)
    monkeypatch.setattr(fr, "read_role", lambda rpc, role, account: True)
    assert fr.run(rpc=None, dry_run=True) == 2
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 1 and out[0].startswith("FATAL: reconstruction gap: ChangedThreshold")


def test_role_inversion_runs_newest_first():
    tip = {(UPGRADER, DEPLOYER): False, (UPGRADER, SAFE): True, (VERIFIER, A): False, (ADMIN, B): True}
    logs = [
        _role_log("RoleGranted", UPGRADER, SAFE, block=10),
        _role_log("RoleRevoked", UPGRADER, DEPLOYER, block=12),
        # inside the batch: A granted, then revoked -> before the batch A did not hold it
        _role_log("RoleGranted", VERIFIER, A, block=13),
        _role_log("RoleRevoked", VERIFIER, A, block=14),
        # and the other way round: B revoked, then granted -> before the batch B held it
        _role_log("RoleRevoked", ADMIN, B, block=15),
        _role_log("RoleGranted", ADMIN, B, block=16),
    ]
    for order in (logs, list(reversed(logs))):  # receipt order must not matter; block/log index decides
        inv = fr.invert(order, [DEPLOYER], 0, 1, tip)
        assert inv.roles == {(UPGRADER, DEPLOYER): True, (UPGRADER, SAFE): False, (VERIFIER, A): False,
                             (ADMIN, B): True}


def test_manifest_hashes_come_from_the_broadcast_records():
    assert fr.read_manifest() == [
        "0x7a99f8092aa924018bab62ab4b0362c9d291376fc96065f614d44a3712288012",
        "0x1f4e63f5d972c9b8b93316da3c2a9dc2707c10a346a3839c0a869475a101853a",
        "0xfa89432ecd8824a96597165e8402a93f7d1405a3ae2f2bc3a1ee0d6e675455cd",
        "0x84977e0e9aead685a5cdf2750b38d81e1dd623d981e596ea25ac1f3a571115a8",
        "0x631857c34f36401a0d503cdc3bbe75ebae2c16aaa090163c06b5ce231b034f55",
    ]


def test_missing_record_is_a_gap(tmp_path):
    with pytest.raises(fr.Gap, match="SafeOwnerSwap"):
        fr.read_manifest(tmp_path)
