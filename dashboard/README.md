# BioRig demo dashboard

Streamlit + web3.py against BioRigCoreV5 behind the ERC1967Proxy on Celo Sepolia (chain 11142220).
The verifier key stays on the machine running Streamlit; the browser never sees it.

```bash
.venv/bin/pip install -r tools/requirements.txt   # once
.venv/bin/streamlit run dashboard/app.py           # http://localhost:8501
```

Needs `.env` with `RPC_URL`, `CHAIN_ID` and `PRIVATE_KEY` (an account holding `VERIFIER_ROLE`).

| file | role |
| --- | --- |
| `config.py` | proxy resolution: `broadcast/DeployAll.s.sol/<chain>/run-latest.json`, then `broadcast/DeployBioRig.s.sol/...`, then `PROXY_ADDRESS` in `.env`; otherwise a loud error listing what was tried |
| `h3_nullifier.py` | lat/lng → H3 cell (res 12) → `keccak256(uint64(cell) ++ utf8(salt))`, asserted to be a non-zero 32-byte value |
| `chain.py` | reads (`getTreeStats`, `isNullifierActive`, `tokenURI`), TBA derivation, `eth_call` simulation, signed `mintTree` |
| `app.py` | the screen: form + simulation + confirm-then-mint on the left, live state + TBA on the right |
| `smoke.py` | headless, read-only proof against the live proxy: `.venv/bin/python -m dashboard.smoke` |

**Mint flow.** Every change to the form re-runs an `eth_call` of `mintTree` from the verifier account and shows
the result (the token id it would mint and a gas estimate, or the decoded revert such as `NullifierInUse()`).
The Mint button stays disabled until that simulation succeeds and the confirmation box is ticked; `send_mint`
simulates once more before it signs.

**Token-bound account.** Derived the way `mintTree` creates it: `salt = keccak256(abi.encodePacked(tokenId,
planter, spatialNullifier))`, then the canonical registry's CREATE2 address for
`(erc6551Implementation, salt, chainId, proxy, tokenId)`. The planter is read from the mint's `Transfer` log, so a
later transfer of the NFT does not change the answer. The screen shows the offline derivation, the registry's own
`account()` and the `tbaAddress` stored in `getTreeStats` side by side, plus the account's `token()` binding.

Tests: `.venv/bin/python -m pytest -q dashboard`.
