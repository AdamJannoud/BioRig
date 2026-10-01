# Deploy the demo dashboard to an independent, public, free host

The dashboard now runs publicly at `https://biorigdemo.streamlit.app` (Streamlit Community Cloud, deployed 1 October
2026) as well as locally from any checkout (`streamlit run dashboard/app.py`). This file records how the public host
was set up, and is the route to redeploying it or moving it to another free host. Two hosts are covered:

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
| `dashboard/deployment.json` | static per-chain record of real deployments, plus the default chain. It holds two: Celo Sepolia (chain id `11142220`, proxy `0x21ab…f7e6`, deploy block `37511856`) and Celo mainnet (chain id `42220`, proxy `0x04db…4e64`, deploy block `78935900`, recorded 1 October 2026). Celo mainnet is the default, so the host renders the mainnet proxy and its live tree with no broadcast artifacts and no secrets; `CHAIN_ID = 11142220` renders Celo Sepolia instead. |
| `dashboard/chains.json` | per-chain registry: name, RPC, explorer, Blockscout verifier, canonical ERC-6551 registry, for Celo Sepolia and Celo mainnet. |
| `.env.example` | every setting the dashboard reads, with the hosted ones marked. |
| `tools/requirements.txt` | local tooling only (video generator, pytest, playwright) and deliberately not the deployed list. |

The proxy address resolves in this order, first hit wins: `broadcast/DeployAll.s.sol/<chain>/run-latest.json`,
`broadcast/DeployBioRig.s.sol/<chain>/run-latest.json`, `PROXY_ADDRESS` from `.env` / `st.secrets` / the
process environment, then `dashboard/deployment.json`. The chain is `CHAIN_ID` if set, else the record's
`default_chain_id`; its RPC endpoint and explorer URL come from `dashboard/chains.json` unless `RPC_URL` /
`EXPLORER_URL` override them. So a hosted instance needs no configuration at all to render the default chain;
secrets only pick another chain, add the signing account and change from read-only to interactive. The hosted
read-only demo needs no secrets, `PRIVATE_KEY` included: do not paste a key unless the instance should simulate
or sign mints.

## 1. Repository state (done — pushed 2026-09-30)

`main` on <https://github.com/AdamJannoud/BioRig> already carries the entrypoint `streamlit_app.py`, the
pinned `requirements.txt`, `.streamlit/config.toml`, `dashboard/` and `dashboard/deployment.json`, alongside
the contracts and the test suite. Deploy from the head of `main`.

For reference: the entrypoint landed in `fee46b9`, `d56b8b5` was a deploy-doc update, and `7911216` is the
commit that added the regenerated architecture diagram and its README section. `7911216` was the head of
`main` when this section was written. Treat the hash as a landmark rather than a pin — commits that only
touch documentation, including the one that wrote this sentence, keep moving the tip. `git ls-remote
origin refs/heads/main` gives the live tip, and what a deploy needs is the entrypoint, which is on `main`.

The repository is public, so Streamlit's picker lists it without any extra GitHub-app grant, and a
reviewer following the repository link opens it directly rather than getting a 404. The running app is
public too — reviewers need only the `*.streamlit.app` URL, not the source.

This branch is `master` locally and was pushed to `main` remotely, so nothing on GitHub is named `master`.

## 2. Deploy on Streamlit Community Cloud

1. Open <https://share.streamlit.io> and sign in with GitHub.
2. Click **Create app** (top right), then **Yup, I have an app**.
3. Fill in:
   - **Repository**: `AdamJannoud/BioRig`
   - **Branch**: `main`
   - **Main file path**: `streamlit_app.py`
4. Optionally set the **App URL** subdomain — the deployed app uses `biorigdemo`, giving `https://biorigdemo.streamlit.app`.
5. Open **Advanced settings**:
   - **Python version**: `3.12` (the platform default; the pins work there).
   - **Secrets**: optional. Leave empty for the read-only demo; otherwise paste the block in the next section.
6. Click **Deploy**. First build takes a few minutes; the log pane on the right shows `pip install` progress
   and any error.
7. Afterwards, **App settings → Sharing** controls who can open it. Keep it public for reviewers; the URL is
   the one to submit.

### Optional secrets (Advanced settings → Secrets)

None of these is required; the public read-only demo runs with the field empty.

```toml
# Same keys as .env, never committed. Leave a key out and the default applies: the record's default chain,
# Celo mainnet (42220), and that chain's RPC from dashboard/chains.json. The public instance sets no CHAIN_ID;
# uncomment the line below only to render Celo Sepolia, the demo tree the video and the screenshots show.
# CHAIN_ID = 11142220
# PRIVATE_KEY = "0x<64 hex digits>" # optional; only to simulate/sign as the VERIFIER_ROLE account
PROXY_ADDRESS = ""                 # empty is fine: dashboard/deployment.json is the fallback
ALLOW_MINT = false                 # false = read-only; true = visitors can broadcast a real mintTree
```

`PRIVATE_KEY`, when set, must be a 32-byte hex key: `0x` plus 64 hex digits, or the 64 digits bare. Paste the
key itself, not the JSON a secret store wraps it in. A malformed value does not take the page down: the app drops
to read-only and shows one warning naming the length and the index of the first invalid character, never the value.

`ALLOW_MINT` is the one decision worth making deliberately. The app signs with the server-side verifier key,
so with `true` **anyone who opens the URL can spend that key's CELO by minting a tree**. The default chain is
Celo mainnet, where the key spends real CELO and mints real tokens: keep `ALLOW_MINT = false` on any public
mainnet instance, the public one included. On a Celo Sepolia instance (`CHAIN_ID = 11142220`) it is only testnet
CELO, but set `false` there too if the URL will be passed around widely; the form and the `eth_call` simulation
still work, only the broadcast button disappears.

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
4. Optional, skip it for the read-only demo. **Settings → Variables and secrets → New secret**: add whichever
   keys from the TOML block above you need, one per entry (`CHAIN_ID`, `PRIVATE_KEY`, `ALLOW_MINT`).
5. The Space builds on push; the URL is `https://huggingface.co/spaces/<user>/<space>`.

## 4. Check the deployed instance

- The page should show the status bar with the chain's name and id (Celo mainnet, `42220`, unless
  `CHAIN_ID` says otherwise), the proxy address and the block number. If it shows a red "Could not resolve the
  BioRig proxy address" panel, the resolution failed everywhere, which on a hosted instance means
  `dashboard/deployment.json` is missing from the deployed commit or records no deployment for that chain.
  `CHAIN_ID=<id> .venv/bin/python scripts/check-hosted-entrypoint.py` runs the same checks locally.
- `Live state · getTreeStats(1)` must show the real tree (on Celo mainnet: DBH 10, biomass 20, alive, token-bound
  account `0x453e89520DB8f374CFCeA95625B99DF5d4F1256A`); that proves the RPC is reachable from the host.
- With `ALLOW_MINT=false`, expect the blue read-only notice above the confirm box instead of an enabled
  **Mint tree** button.
- A yellow "Signing disabled, showing read-only telemetry" warning means `PRIVATE_KEY` is set but is not a
  32-byte hex key; fix or remove the secret. The telemetry above is still live.

## 5. What the hosted instance cannot do

- It cannot read `broadcast/` from a deployment that excluded it, or `PRIVATE_KEY` from a local `.env`; both
  are covered by the static record and the Secrets field.
- It does not run the video generator or the browser-based checks in `scripts/verify-demo.sh`. Those stay
  local (`pip install -r tools/requirements.txt`).
- If you configure a verifier key, it lives in the host's secret store. It is still a real key: on Celo Sepolia fund it with
  testnet CELO only; on Celo mainnet `VERIFIER_ROLE` names the deployer key
  `0x1DB0084Db70bF8D0E06c1785D693Fc6a95317890`, the address step 7 settled on 1 October 2026, and a dedicated key
  once the Safe that holds `DEFAULT_ADMIN_ROLE` grants the role to one.
