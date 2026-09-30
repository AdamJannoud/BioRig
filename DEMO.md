# BioRig demo: dashboard + 90-second explainer

Two pieces for the Celo grant showcase, both against the live deployment on Celo Sepolia (chain 11142220):
proxy `0x21ab8B36177F65ce69e04e281E4aFf3Db6b5f7E6`.

## Setup (once)

```bash
python3 -m venv .venv && .venv/bin/pip install -r tools/requirements.txt
cp .env.example .env   # then fill RPC_URL, CHAIN_ID, PRIVATE_KEY (a VERIFIER_ROLE account)
```

## Dashboard

```bash
.venv/bin/streamlit run dashboard/app.py
```

See `dashboard/README.md` for what each panel does. The Mint button broadcasts a real `mintTree` from the
server-side key, and only after a successful `eth_call` simulation and an explicit confirmation.

## Video

```bash
.venv/bin/python tools/generate_demo.py            # assets/media/demo_90s.mp4, 1920x1080, 30 fps, 90.000 s
.venv/bin/python tools/generate_demo.py --draft    # 854x480 at 12 fps, quick review
.venv/bin/python tools/generate_demo.py --voiceover        # also demo_90s_voiceover.mp4 (gTTS, needs network)
.venv/bin/python tools/generate_demo.py --refresh-facts    # re-read on-chain values into tools/demo_facts.json
.venv/bin/python tools/generate_demo.py --scene 4          # one scene only
.venv/bin/python tools/generate_demo.py --still 78         # PNG of the frame at 01:18
```

| scene | time | frames @30 | module |
| --- | --- | --- | --- |
| 1 Context | 00:00-00:20 | 600 | `tools/demo_scenes/scene1_context.py` |
| 2 Off-chain verification | 00:20-00:45 | 750 | `tools/demo_scenes/scene2_verify.py` |
| 3 On-chain minting | 00:45-01:10 | 750 | `tools/demo_scenes/scene3_mint.py` |
| 4 Protection and solvency | 01:10-01:30 | 600 | `tools/demo_scenes/scene4_protect.py` |

The master is silent with burned-in captions. Every on-chain value on screen (addresses, the token #1 mint tx,
block, gas, TBA, bufferPool) comes from `tools/demo_facts.json`, written by `--refresh-facts` from the live proxy.

What the video deliberately labels as not live, because the deployed contract does not do it:

- **20% buffer-pool split: roadmap, not yet implemented.** `bufferPool` is a stored address with an admin-only
  `setBufferPool` and a `BufferPoolUpdated` event; `mintTree` is non-payable and moves no value.
- **zk-ML proofs: roadmap.** The contract verifies no proof; it trusts the `VERIFIER_ROLE` account.
- The biomass chart in scene 4 is an illustrative series (token #1 has no `GrowthUpdated` events yet).

## Verify everything

```bash
scripts/verify-demo.sh                 # unit tests, live chain smoke, browser check, render + ffprobe, secret scan
SKIP_RENDER=1 scripts/verify-demo.sh   # same, probing the existing mp4 instead of re-rendering
```
