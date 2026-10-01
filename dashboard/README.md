# BioRig demo dashboard

Streamlit + web3.py against BioRigCoreV5 behind the ERC1967Proxy on whichever chain `CHAIN_ID` selects; unset,
the default chain in `deployment.json`, which is Celo mainnet (chain 42220), the deployment the hosted page renders,
with its one live tree. Celo Sepolia (chain 11142220) is recorded beside it: set `CHAIN_ID=11142220` to point the
page at the testnet deployment the demo video shows.
The verifier key stays on the machine running Streamlit; the browser never sees it.

BioRig is Adam Jannoud's project: project lead, author of the contract and the tooling, and the sole deployer of the
addresses this page reads on both Celo Sepolia and Celo mainnet.

```bash
.venv/bin/pip install -r requirements.txt          # the dashboard's runtime deps
.venv/bin/streamlit run dashboard/app.py           # http://localhost:8501
```

The video generator and the test tooling are a separate list: `pip install -r tools/requirements.txt`.

Every setting is optional. Locally, `.env` may supply `RPC_URL`, `CHAIN_ID` and `PRIVATE_KEY`; hosted, the same
keys arrive through `st.secrets`. With none of them the page renders the default chain read-only.

`PRIVATE_KEY` only adds signing: the eth_call simulation and, with `ALLOW_MINT=true`, the mint button, both from
that account (which needs `VERIFIER_ROLE`). When set it must be a 32-byte hex key, `0x` followed by 64 hex digits
or the 64 digits bare. Anything else (wrong length, a stray character, a JSON blob from a secret store pasted
whole) is rejected at load time: the page stays up read-only and shows one warning with the value's length and
the index of the first bad character, never the value. `ALLOW_MINT=false` keeps the simulation while removing the
button that broadcasts a real mint. Deploying to a public host: see `DEPLOY_DASHBOARD.md`; the hosted read-only
demo needs no key at all.

| file | role |
| --- | --- |
| `config.py` | chain selection (`CHAIN_ID`, else the record's default chain, else a loud error listing the registered chains) and proxy resolution: `broadcast/DeployAll.s.sol/<chain>/run-latest.json`, then `broadcast/DeployBioRig.s.sol/...`, then `PROXY_ADDRESS` from `.env` / `st.secrets` / the process env, then `deployment.json`; otherwise a loud error listing what was tried. `python3 -m dashboard.config get <field>` / `env` / `chains` prints the registry for the shell scripts |
| `chains.json` | the per-chain registry (name, RPC, explorer, Blockscout verifier, canonical ERC-6551 registry and its codehash) for Celo Sepolia and Celo mainnet; also read by `script/DeployCommon.sol` |
| `deployment.json` | committed per-chain record of real deployments (`default_chain_id`, then proxy and deploy block per chain id), so a hosted checkout with no broadcast artifacts and no secrets still renders. Written by `scripts/record_deployment.py` from a broadcast, never by hand; the older flat shape is still read |
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

Tests: `.venv/bin/python -m pytest -q dashboard` runs the chain-dependent tests once per registered chain;
`--chain-id 42220` narrows them to one.
