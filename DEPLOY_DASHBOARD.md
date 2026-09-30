# Deploy the demo dashboard to an independent, public, free host

The dashboard currently runs at `https://forge-capability-check-h7z1dd.bolter.run:8501`, which is reachable
from this chat only and stops when the sandbox sleeps. This file is the route to a public URL on a free host
that has nothing to do with this runtime, suitable for Celo reviewers. Two hosts are covered:

- **Streamlit Community Cloud** (primary): free, public, permanent URL at `*.streamlit.app`, deploys straight
  from a GitHub repository.
- **Hugging Face Spaces** (alternative): free CPU Space at `huggingface.co/spaces/<user>/<space>`.

Both run the same repository: the entrypoint at the root, `streamlit_app.py`, starts `dashboard/app.py`.

## What is already prepared in the repository

| path | why it exists |
| --- | --- |
| `requirements.txt` | the dashboard's runtime dependencies only: `streamlit`, `web3`, `eth-account`, `h3`, pinned. Read from the repository root (or from the entrypoint's directory) by both hosts. |
| `.streamlit/config.toml` | Streamlit runtime config: accent colour, headless, no usage stats. |
| `streamlit_app.py` | the entrypoint both hosts look for by default; it runs `dashboard/app.py` rather than a copy of it. |
| `dashboard/deployment.json` | static record of the live deployment (chain id `11142220`, proxy `0x21ab…f7e6`, deploy block `37511856`), so the page renders with no broadcast artifacts and no secrets. |
| `.env.example` | every setting the dashboard reads, with the hosted ones marked. |
| `tools/requirements.txt` | local tooling only (video generator, pytest, playwright) and deliberately not the deployed list. |

The proxy address resolves in this order, first hit wins: `broadcast/DeployAll.s.sol/<chain>/run-latest.json`,
`broadcast/DeployBioRig.s.sol/<chain>/run-latest.json`, `PROXY_ADDRESS` from `.env` / `st.secrets` / the
process environment, then `dashboard/deployment.json`. The chain id, RPC endpoint
(`https://forno.celo-sepolia.celo-testnet.org`) and explorer URL have static defaults in `dashboard/config.py`.
So a hosted instance needs no configuration at all to render; secrets only add the signing account and
change from read-only to interactive.

## 1. Repository state (done — pushed 2026-09-30)

`main` on <https://github.com/AdamJannoud/BioRig> is at commit `a9e24df` and already carries the entrypoint
`streamlit_app.py`, the pinned `requirements.txt`, `.streamlit/config.toml`, `dashboard/` and
`dashboard/deployment.json`, alongside the contracts and the test suite. Deploy from the head of `main`.

That head has moved twice and will move again: `f863608` brought the entrypoint, `a9e24df` the regenerated
architecture diagram and its README section. The hash is a landmark, not a pin. `git ls-remote
origin refs/heads/main` gives the current tip; what the deploy needs is the entrypoint, and it is on `main`.

The repository is private. Streamlit's free tier deploys one private repository, so this works as it stands;
if the picker will not list it, either grant the Streamlit GitHub app access to `BioRig` or make the
repository public. Either way the running app is public — reviewers need only the `*.streamlit.app` URL,
not the source.

This branch is `master` locally and was pushed to `main` remotely, so nothing on GitHub is named `master`.

## 2. Deploy on Streamlit Community Cloud

1. Open <https://share.streamlit.io> and sign in with GitHub.
2. Click **Create app** (top right), then **Yup, I have an app**.
3. Fill in:
   - **Repository**: `AdamJannoud/BioRig`
   - **Branch**: `main`
   - **Main file path**: `streamlit_app.py`
4. Optionally set the **App URL** subdomain, e.g. `biorig-demo`, giving `https://biorig-demo.streamlit.app`.
5. Open **Advanced settings**:
   - **Python version**: `3.12` (the platform default; the pins work there).
   - **Secrets**: paste the block in the next section.
6. Click **Deploy**. First build takes a few minutes; the log pane on the right shows `pip install` progress
   and any error.
7. Afterwards, **App settings → Sharing** controls who can open it. Keep it public for reviewers; the URL is
   the one to submit.

### Secrets to paste (Advanced settings → Secrets)

```toml
# Same keys as .env, never committed. Leave a key out and its static default applies.
RPC_URL = "https://forno.celo-sepolia.celo-testnet.org"
CHAIN_ID = 11142220
PRIVATE_KEY = "0x..."              # account holding VERIFIER_ROLE; omit for a read-only page
PROXY_ADDRESS = ""                 # empty is fine: dashboard/deployment.json is the fallback
ALLOW_MINT = false                 # false = read-only; true = visitors can broadcast a real mintTree
```

`ALLOW_MINT` is the one decision worth making deliberately. The app signs with the server-side verifier key,
so with `true` **anyone who opens the URL can spend that key's testnet CELO by minting a tree**. That is the
point of the demo and it is only Celo Sepolia, but set `false` if the URL will be passed around widely; the
form and the `eth_call` simulation still work, only the broadcast button disappears.

## 3. Alternative: Hugging Face Spaces

1. Create a Space: <https://huggingface.co/new-space>, SDK **Streamlit**, hardware **CPU basic (free)**,
   visibility public.
2. The Space's `README.md` needs this front matter above the text:

```yaml
---
title: BioRig Demo
emoji: 🌳
colorFrom: green
colorTo: blue
sdk: streamlit
sdk_version: 1.64.0
app_file: streamlit_app.py
pinned: false
---
```

3. Push this repository to the Space remote. Only `streamlit_app.py`, `requirements.txt`,
   `.streamlit/config.toml`, and `dashboard/` are needed to run; pushing the whole checkout is fine too. The
   front matter above goes at the top of the repository's `README.md`, above the existing text (it is inert
   for Streamlit Cloud and for GitHub).
4. **Settings → Variables and secrets → New secret**: add the same keys as the TOML block above, one per
   entry (`RPC_URL`, `CHAIN_ID`, `PRIVATE_KEY`, `ALLOW_MINT`).
5. The Space builds on push; the URL is `https://huggingface.co/spaces/<user>/<space>`.

## 4. Check the deployed instance

- The page should show the status bar with chain `11142220`, the proxy address and the block number. If it
  shows a red "Could not resolve the BioRig proxy address" panel, the resolution failed everywhere, which on
  a hosted instance means `dashboard/deployment.json` is missing from the deployed commit.
- `Live state · getTreeStats(1)` must show the real tree; that proves the RPC is reachable from the host.
- With `ALLOW_MINT=false`, expect the blue read-only notice above the confirm box instead of an enabled
  **Mint tree** button.

## 5. What the hosted instance cannot do

- It cannot read `broadcast/` from a deployment that excluded it, or `PRIVATE_KEY` from a local `.env`; both
  are covered by the static record and the Secrets field.
- It does not run the video generator or the browser-based checks in `scripts/verify-demo.sh`. Those stay
  local (`pip install -r tools/requirements.txt`).
- The verifier key lives in the host's secret store. It is still a real key: fund it with testnet CELO only.
