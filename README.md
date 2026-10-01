# BioRig

`BioRigCoreV5` is an upgradeable (UUPS) ERC-721 where one token is one planted, monitored tree. Every mint
carries a 32-byte spatial nullifier, so the same plot cannot be registered twice, and every tree gets an
ERC-6551 token-bound account created through the canonical registry.

Live on **Celo Sepolia** (chain id `11142220`), all four contracts verified on Blockscout:

| contract | address |
| --- | --- |
| BioRigCoreV5 (implementation) | `0x4c998c6553c78bb9d5a67aac6fbc526d64dba3a4` |
| ERC1967Proxy (the live address) | `0x21ab8b36177f65ce69e04e281e4aff3db6b5f7e6` |
| ERC-6551 account implementation | `0x3d8a53db1bbcab6d47097b25080527e5560c5165` |
| ERC-6551 registry (canonical) | `0x000000006551c19487814612e58FE06813775758` |

Proxy deployed in block `37511856`; that address also lives in `dashboard/deployment.json`.

**Celo mainnet** (chain id `42220`) is approved as an Alpha v1 / pilot deployment and is **not deployed yet**. The
ordered runbook, with the post-broadcast handover of admin to a Safe and of `VERIFIER_ROLE` to a dedicated key, is
`DEPLOY.md` section 8. Both chains are configured in one place, `dashboard/chains.json`.

**How the nullifier is derived.** The production derivation is `keccak256(uint64(h3Cell) ++ utf8(salt))` with the
cell taken at H3 resolution 12, implemented in `dashboard/h3_nullifier.py`. The contract is looser than that:
`mintTree` stores the 32-byte value the verifier passes and rejects only `bytes32(0)`, so the H3 derivation is
an off-chain convention, not an on-chain rule. The one tree live on this deployment was minted from the bare
salt as a demo, so token 1's stored nullifier is `keccak256("plot-1")` and does not exercise the H3 pipeline.
Section 4 of `DEPLOY.md` records that mint, with both digests.

## Architecture

![BioRig end-to-end system architecture](BioRig_Architecture_Pro.png)

Four tiers, top to bottom. **Off-chain edge capture** (mobile dMRV, the H3 spatial nullifier, the zk-ML
prover) is untrusted: the contract executes and verifies none of it. The handoff into the chain is a
verifier-signed `mintTree` carrying the nullifier, DBH and biomass; `mintTree` takes no proof, so the trust
boundary is `onlyRole(VERIFIER_ROLE)`, not cryptography. **On-chain execution** is the four deployed contracts
above, with the token-bound account created through the canonical ERC-6551 registry at
`keccak256(tokenId ++ planter ++ nullifier)`. The **protocol tier** (carbon accrual, the 20% buffer pool,
ReFi rails, demand side) is roadmap and badged as such on every box. The **demo dashboard** runs today; its
public host is still being deployed, so the diagram marks it in progress and prints no URL.

The PNG (4800 px wide) and its vector source `assets/BioRig_Architecture_v5.svg` are generated, not drawn:
`tools/generate_architecture.py` reads every address from `dashboard/deployment.json` and the DeployAll
broadcast, and `tools/test_architecture.py` fails if any address in the scene, the SVG or the PNG's pixels
(read back with tesseract) drifts from that record. After a redeploy:

```bash
.venv/bin/python tools/generate_architecture.py            # rewrite the SVG and PNG, byte-identical on rerun
.venv/bin/python -m pytest -q tools/test_architecture.py
```

## Layout

| path | what it is |
| --- | --- |
| `src/` | `BioRigCoreV5.sol` and the vendored ERC-6551 pieces |
| `test/` | Foundry test suite (`forge test`) |
| `script/` | deployment scripts, including `DeployAll.s.sol`, which deployed the live addresses |
| `dashboard/` | Streamlit + web3.py demo dashboard over the live proxy |
| `tools/` | the 90-second explainer video generator, and the architecture diagram generator |
| `broadcast/` | the recorded deployment run the dashboard reads its proxy address from |
| `scripts/verify-demo.sh` | one command that checks all of the above and exits non-zero on any failure |

## Docs

- `DEPLOY.md` - deploying and verifying the contracts.
- `DEMO.md` - the dashboard and the explainer video, and how to run them.
- `DEPLOY_DASHBOARD.md` - putting the dashboard on a free public host (Streamlit Community Cloud, Hugging Face Spaces).
- `FINDINGS.md`, `HARDENING.diff` - the audit round and the hardening change it produced.

## One note for reviewers

The 20% buffer-pool split shown in the demo video is **roadmap, not a live feature**: in `BioRigCoreV5`,
`bufferPool` is a stored address with an admin-only setter and an event, and `mintTree` is non-payable. The
video labels it as roadmap, and `scripts/verify-demo.sh` checks that the label is burned into the rendered
frames rather than trusting the source.

## Quick start

```bash
forge test                                                    # contract suite
pip install -r requirements.txt                               # dashboard runtime
.venv/bin/streamlit run dashboard/app.py                      # dashboard, http://localhost:8501
bash scripts/verify-demo.sh                                   # the full acceptance check
.venv/bin/python scripts/check-hosted-entrypoint.py            # the deployable dashboard, as a host runs it
```
