# BioRig

`BioRigCoreV5` is an upgradeable (UUPS) ERC-721 where one token is one planted, monitored tree. Every mint
carries a spatial nullifier derived from the plot's H3 cell, so the same plot cannot be registered twice, and
every tree gets an ERC-6551 token-bound account created through the canonical registry.

Live on **Celo Sepolia** (chain id `11142220`), all four contracts verified on Blockscout:

| contract | address |
| --- | --- |
| BioRigCoreV5 (implementation) | `0x4c998c6553c78bb9d5a67aac6fbc526d64dba3a4` |
| ERC1967Proxy (the live address) | `0x21ab8b36177f65ce69e04e281e4aff3db6b5f7e6` |
| ERC-6551 account implementation | `0x3d8a53db1bbcab6d47097b25080527e5560c5165` |
| ERC-6551 registry (canonical) | `0x000000006551c19487814612e58FE06813775758` |

Proxy deployed in block `37511856`; that address also lives in `dashboard/deployment.json`.

## Layout

| path | what it is |
| --- | --- |
| `src/` | `BioRigCoreV5.sol` and the vendored ERC-6551 pieces |
| `test/` | Foundry test suite (`forge test`) |
| `script/` | deployment scripts, including `DeployAll.s.sol`, which deployed the live addresses |
| `dashboard/` | Streamlit + web3.py demo dashboard over the live proxy |
| `tools/` | the 90-second explainer video generator |
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
