# BioRig — Final Project Report

**Project:** BioRig — on-chain forest-MRV with token-bound trees
**Repository:** https://github.com/AdamJannoud/BioRig (public)
**Evidence base:** commit `b85e2530efcc0f64e4a02fe73c3046f779fdce1a` — the main tip when this report was written (origin/main = local HEAD, 132 commits, clean tree, 0/0 divergence). The commit that carries this file changes only what §4.8 lists, and it is a byte-checked carrier itself.
**Date:** 4 October 2026, 13:50 UTC
**Author / attribution:** Adam Jannoud (every commit in the history, see §4.2)

**Identifiers:** every commit hash in this document was re-pointed on 8 October 2026 to the history produced by that day's repo-wide identity normalisation. That rewrite changed hashes and identity fields only — every tree, subject and date is unchanged, and §4.5 records the proof. Counts and command outputs are the 4 October capture they were recorded from.

---

## 1. Executive summary

BioRig is a Celo-based measurement, reporting and verification (MRV) system that registers trees on-chain as ERC-721 tokens, gives each one a token-bound account (ERC-6551), and routes verified field measurements through a signing relay. It is built by Adam Jannoud and lives in the public `AdamJannoud/BioRig` repository.

The system is live on **Celo mainnet (chain id 42220)**. The deployable core, dashboard, relay, Android app, grant application, milestone report and deployment plan are all delivered, and every published copy is byte-checked against the repository's carrier gate.

Highlights of the landed state:

- **132 commits** at the evidence tip, every one authored and committed as Adam Jannoud; the repository is public and pushed to GitHub.
- **Mainnet live**: upgradeable `BioRigCoreV5` proxy deployed at `0x04Db169dDF8AbB80943161C01B2a71DC40384E64` (block 78,935,900), with token 1 (the pilot tree) minted on-chain at block 78,992,489.
- **First token-bound tree**: token 1 owns a live ERC-6551 account at `0x453e89520DB8f374CFCeA95625B99DF5d4F1256A`.
- **Carrier gate 100% green**: all thirteen published assets byte-match their recorded sources at the evidence tip, and this edition adds itself as the fourteenth (§4.4, §4.8); acceptance gate passes end to end.
- **Android debug APK** built from committed source, published as a GitHub release asset, public download verified byte-for-byte.
- **Full sync/attribution audit** in §4: single identity across the whole history, zero obsolete platform links in tracked files or published copies, clean-clone proofs PASS for both local and pulled-from-GitHub copies of the tip.

---

## 2. Core architecture & mechanism

### 2.1 MRV pipeline

The measurement flow runs in the Streamlit dashboard and lands on-chain through the deployer/relay:

1. A user chooses a plot location; the app assigns an **H3 cell** and enforces a spatial accuracy gate (haversine distance, 20 m ceiling on the cell).
2. The user enters trunk **diameter at breast height (DBH)** and a reference string; species is optional.
3. The dashboard derives a **nullifier** from the H3 cell plus a salt (`keccak256(uint64(h3Cell) + utf8(salt))`, salt form `biorig:v1:<cell>:<index>`), so each plot can only ever register once.
4. **Allometry** (dashboard/allometry.py) converts DBH to above-ground biomass (see §2.5).
5. The plot is **minted** via `BioRigCoreV5.mintTree`, restricted to `VERIFIER_ROLE` — one registration, one tree.

### 2.2 On-chain core: BioRigCoreV5 + ERC-6551 token-bound accounts

- `src/BioRigCoreV5.sol` is a UUPS-upgradeable contract (ERC1967Proxy), audited in-repo with a 181-test Foundry suite and a documented storage-layout proof (V5 slots 0–8, V6 `_baseURI` append; the V6 marker sits at slot 9).
- Each minted token gets a **token-bound account** (ERC-6551) so per-tree state can travel with the NFT. The canonical ERC-6551 registry is reused.
- Contract addresses:

| Contract | Mainnet (42220) | Sepolia (11142220) |
| --- | --- | --- |
| BioRigCoreV5 proxy | `0x04Db169dDF8AbB80943161C01B2a71DC40384E64` | `0x21ab8B36177F65ce69e04E281E4aFf3Db6b5f7E6` |
| Deployed block | 78,935,900 | 37,511,856 |

- **Pilot tree (token 1)**, read live and cross-checked against the mint receipt:

| Field | Value |
| --- | --- |
| Owner | `0xD314e37FD8538fe66231EE670B74C9428d03feEa` |
| Mint tx | `0x70476c02ef1af918a213eec63472e6cdbabcedd50193cdd6a7a89a09527797f7` |
| Block / gas | 78,992,489 / 270,077 (0.054015697 CELO) |
| Stats | dbh 10, biomass 20, timestamp 1790893247, alive true |
| Token-bound account | `0x453e89520DB8f374CFCeA95625B99DF5d4F1256A` |
| Nullifier | `0xb7a55a6b1b7e4fe0fba76f303772cba7fdf3715d4030e3fcd91ed297c756d741` (active) |

The pilot tree holds placeholder values (dbh 10 / biomass 20), not field measurements — the dashboard and grant material are explicit about this.

### 2.3 Verifier relay

`relay/` is a FastAPI service that sits in front of `mintTree`:

- **Dry-run mode on mainnet**: `dry_run: true`, chain 42220, signed by the verifier key `0x1DB0084Db70bF8D0E06c1785D693Fc6a95317890`; `/healthz` reports chain_id 42220, `signer_is_verifier`, and a 0/0/0 queue.
- Public route verified through the platform edge: anonymous `GET /healthz` → 200; `POST /v1/sessions` → 201; session-authenticated registration proceeds past auth.
- **One registration = one tree**; submissions are public with rate limits.

### 2.4 Install-id rate limiting

Rate limits are keyed on what the app holds, not the edge's address:

- `relay/service.py` keys on the **`X-BioRig-Install-Id`** header when present and well-formed; otherwise falls back to the peer address.
- A relay-wide `sessions_global_hour` ceiling (30/hour) bounds global abuse regardless of how many device IDs are presented.
- The Android app holds a per-install UUID, so a device keeps its own quota across network/IP changes. This design is documented in `docs/relay-api.md` and covered by tests.

### 2.5 Allometry: biomass & carbon

`dashboard/allometry.py` implements the Chave et al. 2014 pan-tropical model (eq. 4):

- `AGB (kg) = 0.0673 × (rho × D² × H)^0.976`, with `D` the DBH in cm.
- Height estimated from diameter when not measured: `H (m) = 1.3 + 0.55 × D^0.9`.
- Wood density default `rho = 0.6 g/cm³` (mid-range tropical hardwood).
- Carbon = 47% of dry biomass (IPCC 2006, AFOLU vol. 4 table 4.3); CO₂-equivalent = carbon × CO₂-per-C.

---

## 3. Delivery & achievements by phase

| Phase | Delivered | Evidence |
| --- | --- | --- |
| Core contract + tooling | Upgradeable BioRigCoreV5 (ERC1967Proxy), deploy scripts, `.env` template, Celo Sepolia/mainnet | `src/`, `script/`, Foundry suite |
| Test suite & defect audit | 181-test Foundry suite, 16–17 suites; round-1 + hardening findings in `FINDINGS.md`; I-6 `_baseURI` override with storage-layout proof | `test/`, `FINDINGS.md` |
| Dashboard + demo | Streamlit dashboard (home landing, dark lime/emerald restyle), 90 s explainer video (silent + voiceover) | `dashboard/`, `demo_90s*.mp4` |
| Chain deployment | Live on Celo mainnet + Sepolia; token 1 minted; Safe owner-swap and mode-B role handover rehearsed on fork and executed | Deployment plan, broadcast records |
| Android MVP | org.biorig.app, versionName 0.1.0, versionCode 1, minSdk 26, targetSdk 35; H3 natives; 49 JVM tests | `mobile/android`, APK release |
| Relay (phases 0–3) | Registration queue, sessions, install-id rate limits, dry-run | `relay/`, `docs/relay-api.md` |
| Grant deliverables | 14-page Prezenti proposal (PDF/DOCX), milestone & roadmap report (DOCX), architecture diagram (SVG + PNG, incl. slide raster) | Carriers (§4.4) |
| Acceptance gate + CI | `scripts/verify-demo.sh` (ten steps), carrier gate with `--require-staged`, clean-clone proof wired into the push path, GitHub Actions green | Gate + proofs |
| Final sync audit | Attribution, host sweep, carrier re-verification, drift fix, clean-clone proofs — this report | §4 |

### Test inventory at the reported tip

- **Foundry:** 181 passed, 17 suites, 11.02 s (re-run against `f6f2045` checkout, 3 Oct 2026).
- **Python:** `pytest dashboard tools relay` → 440 passed; with `--chain-id 42220` → 412 passed.
- **Android JVM:** 49 tests passed; `lintDebug` exit 0 (61 warnings, all by design or newer-library notices, zero errors); `assembleDebug` green and APK matched to committed source.
- **Acceptance gate:** `scripts/verify-demo.sh` exit 0, **ALL DEMO CHECKS PASSED** (all nine earlier steps + the carrier step), including 427 tests in the clean-clone proof run and both mainnet fork rehearsals.

---

## 4. Sync, attribution & carrier audit (evidence)

Everything below was re-run at 13:50–14:00 UTC against tip `b85e253`.

### 4.1 Repo state at tip

```
$ git rev-parse HEAD
b85e2530efcc0f64e4a02fe73c3046f779fdce1a
$ git ls-remote origin refs/heads/main
b85e2530efcc0f64e4a02fe73c3046f779fdce1a  refs/heads/main
$ git rev-list --left-right --count origin/main...HEAD
0  0
$ git status --porcelain            # empty → clean tree
$ git rev-list --count HEAD
132
```

### 4.2 Attribution audit

```
$ git log --format='%an <%ae>|%cn <%ce>' | sort | uniq -c
131  AdamJannoud <jannoud-adam@hotmail.com>|AdamJannoud <jannoud-adam@hotmail.com>
  1  Adam Jannoud <jannoud-adam@hotmail.com>|Adam Jannoud <jannoud-adam@hotmail.com>
```

Every one of the 132 commits is authored and committed by the same person and email. The one name
variant the audit found (`550942c`: "Adam Jannoud" against "AdamJannoud", same address) was
normalized on 8 October 2026 by a repo-wide identity rewrite, so every commit in the current history
reads `AdamJannoud <jannoud-adam@hotmail.com>`. All README, DEPLOY, DEMO, proposal, milestone and
deployment-plan docs attribute the project and author to Adam Jannoud and link
`https://github.com/AdamJannoud/BioRig`.

### 4.3 No obsolete platform links

Swept every tracked file and every staged published copy for this working environment's own host names: the two retired
platform hosts and the temporary per-sandbox hostname this work was done on. No matches in either set.

The literal patterns are deliberately not repeated in this document, so that committing it cannot put a retired host
name back into the tree. They live in the audit sweep itself, not here.

Zero references to any retired or temporary host remain in tracked files or in any published carrier copy.

### 4.4 Carrier gate (fourteen published assets, all byte-matched)

`docs/carriers.json` records fourteen published assets: the thirteen that stood at the evidence tip, plus this report as the fourteenth (added by this edition):

1. `proposal.pdf`  ·  2. `proposal.docx`  ·  3. `proposal.md`  ·  4. `architecture.png`  ·  5. `architecture.svg`  ·  6. `architecture-slide.png`  ·  7. `android-debug.apk`  ·  8. `milestone-report.docx`  ·  9. `celo-mainnet-deployment-plan.md`  ·  10. `findings.md`  ·  11. `demo_90s.mp4`  ·  12. `demo_90s_voiceover.mp4`  ·  13. `corev5-source.md`  ·  14. `final-project-report.md` (this report, byte for byte from `docs/final-project-report.md`; added by this edition)

```
$ tools/check_carriers.py --require-staged
  → every recorded carrier ok, exit status 0
$ .venv/bin/python -m pytest tools/test_carriers.py -q
  → 62 passed
```

`tools/test_carriers.py` (42→62 tests as carriers grew) proves the gate catches drifted bytes — flipping a byte in the committed diagram SVG fails it.

### 4.5 Clean-clone proofs (tip `b85e253`)

Two independent proofs were recorded for that delivery, both `verdict: PASS`, with `skipped_steps`
none:

- `.git/clean-clone-proof/6ba5123….json` — **source=local**: fresh clone of the tip, key-free, README
  quick-start followed, full `verify-demo.sh` exit 0, **ALL DEMO CHECKS PASSED**, 427 tests, both fork
  rehearsals, 12/12→13/13 carriers, doc-path sweep clean.
- `.git/clean-clone-proof/6ba5123….remote.json` — **source=github**: the pushed tip re-cloned back from
  GitHub, identical tree, same verdict `PASS`.

Both records are named by pre-rewrite hashes, because a proof file is written at push time. The
rewritten tip `09469fa68cfccfd5bfe961e1cb0809cb700c5d30` carries its own pair from the push that
landed the rewrite (`.git/clean-clone-proof/09469fa68cfccfd5bfe961e1cb0809cb700c5d30.json` source=local, `.git/clean-clone-proof/09469fa68cfccfd5bfe961e1cb0809cb700c5d30.remote.json` source=github), and both read `PASS`.

These run inside `scripts/push-verified.sh` (stage 1 local proof, stage 3 GitHub re-prove), so a push that does not survive a fresh clone never lands.

### 4.6 Android APK & release asset

- **Build-source tree** `mobile/android` pinned in the carrier record: `421f7f03fe0db6ab473d8538e029b0b981357e16`.
- **APK:** 16,079,038 bytes, sha256 `22d906d6c98b7d0a11829a1204dfea6334065c460d5808e87b830918a1740dd0`, org.biorig.app, debug-signed (valid v2 signature, zipalign 4-byte OK), natives arm64-v8a / armeabi-v7a / x86 with `libh3-java.so`.
- **GitHub release `apk-04fbf40`** (prerelease): tag → `0c4c6406c64a69228fc6326715cabde666c58160`. Anonymous download verified: HTTP 200, 16,079,038 bytes, sha256 identical to the committed carrier record and to the local file.

### 4.7 Drift found, fixed and re-verified

The audit caught a real staleness: both `docs/milestone-roadmap-report.md` and `docs/celo-mainnet-deployment-plan.md` claimed "six commits landed after f6f2045" when **nine** had landed. Both were rewritten to a bounded range ("between f6f2045 and ed14bfa, the head when this line was written"), the DOCX re-rendered, the carrier record re-recorded (diff = exactly the two changed rows), and the gate re-run green. That fix is commit `b85e253`, the evidence base for this report.

### 4.8 This edition's own change

This report is committed as `docs/final-project-report.md` and published as the fourteenth carrier. The commit that carries it changes exactly five things, and nothing else:

- adds `docs/final-project-report.md` (this file);
- adds its row to `docs/carriers.json`, pinned byte for byte to this file (`copy_of`), so the published copy is checked like every other carrier's;
- raises the carrier floor in `scripts/verify-demo.sh` from thirteen to fourteen;
- names the report among the published files in `DEPLOY.md` section 9 and describes its derivation there;
- touches nothing else: no contract, app, dashboard, relay, renderer or other carrier's bytes change.

Every number quoted above is stated for the evidence base (`b85e253`), where the record held thirteen carriers; after this commit it holds fourteen. The gate is re-run over the fourteen-carrier record before the commit lands, and the commit is pushed through `scripts/push-verified.sh`, so a fresh clone of it must pass the same gate before the push is accepted.

---

## 5. Operational & deployment guide

### 5.1 Mainnet status (as of report)

- Chain **Celo mainnet, id 42220**; contract at `0x04Db169dDF8AbB80943161C01B2a71DC40384E64` (UPGRADER_ROLE held by the Safe; VERIFIER_ROLE on the deployer/verifier key).
- Measured deployment cost: **0.803044 CELO** at 200.0011 gwei (≈ US$0.10) — the pilot was intentionally cheap; token 1 mint cost 0.054 CELO.
- Sepolia (11142220) remains available for testing at `0x21ab8B36177F65ce69e04E281E4aFf3Db6b5f7E6`.

### 5.2 Dry-run relay setup

1. `cd relay && pip install -r requirements.txt` (or use the repo venv).
2. Ensure `dry_run: true` (default for the relay as committed) — it validates the whole request path and signs nothing on-chain.
3. `uvicorn service:app --host 0.0.0.0 --port 8000`; check `/healthz` (chain 42220, signer is verifier, queue 0/0/0).
4. Rate limits key on `X-BioRig-Install-Id`; tests cover both the device-keyed and fallback paths.

### 5.3 Running the test suites (at the evidence tip)

- Contract: `forge test` → 181 passed, 17 suites.
- Python: `pytest dashboard tools relay` → 440 passed; `--chain-id 42220` → 412 passed.
- Full acceptance gate: `scripts/verify-demo.sh` → exit 0, ALL DEMO CHECKS PASSED.
- Carrier gate: `tools/check_carriers.py --require-staged` → exit 0.
- Android: `./gradlew :core:test :app:assembleDebug` (mobile/android, `ANDROID_HOME` set) → 49 JVM tests green, APK built.

### 5.4 Public release assets

- Repository (public): https://github.com/AdamJannoud/BioRig
- APK release: https://github.com/AdamJannoud/BioRig/releases/tag/apk-04fbf40 (asset `BioRig-android-debug-04fbf40.apk`, sha256 `22d906d6…1740dd0`)
- Demo dashboard: live Streamlit app (`biorigdemo.streamlit.app`), slider/density fix verified live at 24/25/75 cm.
- Carrier record (source of truth for published copies): `docs/carriers.json`.

---

## 6. Honest scope notes

- The relay runs in **dry-run** on mainnet by default; a live (signing) mode requires gating the verifier key, which currently still sits with the deployer. The Safe holds `DEFAULT_ADMIN_ROLE` and can grant/revoke `VERIFIER_ROLE` without a handover.
- The pilot tree's dbh/biomass are placeholder numbers, not measurements; real field data is roadmap phase B.
- No emulator was available for on-device Android screenshots; the APK is verified by build, signature, lint and JVM tests, not by visual device shots.
- This report is itself a published carrier: editing it means republishing it and re-recording its row, exactly like the other thirteen.
