# BioRig Android — the three-step MRV app

A planter walks to a tree and the phone does the indexing. It takes a fix and refuses one worse than 30 m. It
works out the H3 resolution-12 cell and checks the plot index before the planter goes on. It photographs the
trunk and estimates biomass from the diameter the planter enters, with the same allometry the relay uses. Then it
gives the relay a **measurement, not an identity**. Captures are queued in the phone's database and sent when
there is signal.

The contract is [`docs/relay-api.md`](../../docs/relay-api.md) (relay contract v1) plus `relay/` itself. The app
uses exactly its four non-admin routes and sends only the fields it defines.

## Layout

```
mobile/android/
  settings.gradle.kts      :core always; :app only when an Android SDK is found (see below)
  build.gradle.kts         every plugin on the root classpath once, unapplied
  gradle/libs.versions.toml
  core/                    plain Kotlin (JVM 17), no Android dependency: everything here is a JVM test
    src/main/kotlin/org/biorig/core/
      RelayDefaults.kt     the relay's defaults mirrored, incl. SPECIES_OPTIONS (the picker's list)
      allometry/           1:1 port of dashboard/allometry.py (Chave et al. 2014)
      geo/                 H3 via com.uber:h3, haversine, ring_k, the 30 m fix gate, the 20 m collision pre-check
      chain/               keccak256 (Bouncy Castle), EIP-55, the nullifier derivation, a 3-call JSON-RPC reader
      photo/               the photo's EXIF-time / distance check
      relay/               contract-v1 wire types, RelayClient (OkHttp), RegistrationBuilder, planter wording
      queue/               CaptureEntity (the Room row), SubmissionQueue (send, retry, poll)
    src/test/...           JUnit tests + golden/vectors.json (generated, see below)
  app/                     Compose UI, fused location, CameraX, Room; manual constructor injection (AppGraph)
    src/main/.../ui/       Theme.kt (direction B tokens), Screens.kt (six stateless screens), Routes.kt (ViewModel wiring)
    src/test/...           ScreenRenders: the JVM renders behind :app:renderScreens (Robolectric)
    src/androidTest/...    instrumented tests: present, compiled, NOT RUN here (no emulator)
  screenshots/             the six screens x light/dark as PNGs, plus manifest.json (sha256 per render)
  tools/
    gen_golden.py               writes core/src/test/resources/golden/vectors.json from the repo's own Python
    check_registration_body.py  runs the body :core builds through relay/validate.py
    relay_e2e.py                serves the real relay.service.Relay and drives SubmissionQueue against it
```

## What goes to the relay, and what never does

`POST /v1/registrations` carries `submission_id`, `planter_address`, `fix{lat,lng,accuracy_m,captured_at}`,
`tree{species,dbh_cm}`, `client_estimate{biomass_kg,co2e_kg}` and `photo_sha256`. It never carries a nullifier,
salt, cell, ordinal, top-level biomass or token id: the relay derives the plot identity under the cell's write lock
and refuses any of those with `forbidden_field`. The phone computes the cell for its own pre-check and never sends
it. When a job comes back, the app re-derives `keccak256(uint64(cell) ‖ "biorig:v1:<cell>:<ordinal>")` and checks
the relay's nullifier against it.

There is **no key on this phone**. It holds the planter's public address, typed or pasted, which it validates with
the same EIP-55 rule as `relay/validate.py`. It also holds the relay session token, a 24-hour rate-limit key that
is not a credential. The relay holds `VERIFIER_ROLE` and signs `mintTree`. No keystore, mnemonic or signing config
exists in this tree, and `.gitignore` refuses `*.jks` / `*.keystore`.

The trunk photo stays in app-private storage. Only its SHA-256 is sent, because contract v1 has no upload.

## Refusals the app handles

| Relay answer | What the planter sees / what the queue does |
| --- | --- |
| `202 created`, `200 replayed` / `same_tree` / `recovered` | the capture gets its job; polled until `minted` or `rejected` |
| `422 accuracy_too_coarse`, `fix_stale`, `fix_in_future`, `out_of_range` | "take a new fix" at the tree; photo and diameter kept, same submission id |
| `409 collision`, `422 cell_full`, `denylisted_area` | "this plot is taken / full / excluded", with the relay's distance; the planter removes it |
| `422 estimate_mismatch`, `dbh_out_of_bounds` | the relay's figure is shown; re-enter the diameter |
| `422 species_not_allowed` | the relay's `error.allowed` list is offered and becomes the picker's list |
| `429 rate_limited` | waits `Retry-After` (header, else `error.retry_after_s`); not counted as a failure. `limit: per_session` opens a new session at once |
| `401 session_*` | a new session, then the same body again (once) |
| `503 chain_unavailable` / `recovery_pending` / `index_inconsistent`, `500`, no answer | retried with backoff 30 s / 2 min / 10 min; after 4 attempts the planter is asked |
| anything else (`invalid_field`, `unknown_field`, ...) | "this app needs an update"; the capture is kept |

`PlanterMessagesTest` parses the error table in `docs/relay-api.md`. A new 409/422/429/503 code there fails the
build until it has its own wording.

**Species.** `RelayDefaults.SPECIES_OPTIONS` defaults to `["unspecified"]`, the relay's own default allowlist
(`RelayConfig.species` in `relay/config.py`). An operator who sets `RELAY_SPECIES` does not need a new app: the first
`species_not_allowed` brings back `error.allowed`, and the picker offers that list.

## Build and test

### `:core` — needs only JDK 17

```bash
cd mobile/android && ./gradlew :core:test --console=plain
```

This is the command the work is accepted on. It needs `java` on the PATH (Debian/Ubuntu: `apt-get install
openjdk-17-jdk-headless`) and network access the first time, to fetch Gradle 8.10.2 and the dependencies. It
needs no Android SDK and no `JAVA_HOME`.

**How `:app` is kept from breaking it.** The Android Gradle plugin will not configure a module without an SDK, and
Gradle configures every included project before it runs a task. So `settings.gradle.kts` includes `:app` only when
an SDK is found, through `local.properties` `sdk.dir`, `ANDROID_HOME` or `ANDROID_SDK_ROOT`. Without one it prints
`biorig: no Android SDK found ... :app is left out of this build` and builds `:core` alone. With an SDK present,
`-Pbiorig.skipApp=true` leaves `:app` out on purpose. AGP is resolved on the root classpath (`apply false`) so
that it shares a classloader with the Kotlin plugin. Resolving it needs only the Maven repositories; applying it,
which only `:app` does, is what needs the SDK.

### Golden vectors and the relay's own validator — need the repo's `.venv`

```bash
.venv/bin/python mobile/android/tools/gen_golden.py --check     # exit 1 if vectors.json is stale
.venv/bin/python mobile/android/tools/gen_golden.py             # regenerate after a deliberate change
.venv/bin/python mobile/android/tools/check_registration_body.py
.venv/bin/python mobile/android/tools/relay_e2e.py
```

`gen_golden.py` imports `dashboard/allometry.py`, `dashboard/h3_nullifier.py`, `relay/plot_index.py`,
`relay/config.py` and `relay/validate.py`, and writes every allometry row for DBH 2–120. It also writes H3 cells,
k-rings and neighbourhoods for 12 points, 18 salt/preimage/nullifier triples, haversine pairs around the 20 m
boundary, EIP-55 vectors, function selectors, the limits and the field sets. `GoldenVectorsTest` compares `:core`
with all of them. If a constant moves in the Kotlin, the tests fail. If one moves in the Python, `--check` fails,
and regenerating changes the expected values.

`check_registration_body.py` gets the exact body from `./gradlew :core:emitRegistrationBody` and passes it to
`relay.validate.parse_submission` with the relay's default limits and allowlist. Four controls follow: a smuggled
`cell` and a smuggled `nullifier` must be refused `forbidden_field`, a doubled estimate `estimate_mismatch`, and an
unlisted species `species_not_allowed`.

`relay_e2e.py` serves `relay.service.Relay` over HTTP. It builds it the way `relay/tests/conftest.py` does, with
the suite's `FakeBroadcaster` and its no-key `TEST_KEY`, so nothing is signed and no network is touched. It then
runs `:core:relayE2e` through these answers: created, replayed, collision, species_not_allowed then created,
accuracy_too_coarse, plot and job reads, and a 429 with Retry-After.

### `:app` — needs the Android SDK (platform 35, build-tools 35.0.0)

```bash
cd mobile/android
ANDROID_HOME=/path/to/sdk ./gradlew :app:assembleDebug
ANDROID_HOME=/path/to/sdk ./gradlew :app:assembleDebug -Pbiorig.relayUrl=https://relay.example.org
ANDROID_HOME=/path/to/sdk ./gradlew :app:connectedDebugAndroidTest   # device or arm64 emulator attached
```

The relay URL defaults to `http://10.0.2.2:8787`, the emulator's alias for the developer machine, where `python -m
relay` listens on `RELAY_PORT` 8787. Cleartext is allowed for that host only (`res/xml/network_security_config.xml`).
The chain read-back defaults to Celo mainnet: `https://forno.celo.org` and the proxy in
`dashboard/deployment.json`. Override with `-Pbiorig.rpcUrl` / `-Pbiorig.proxy`.

**H3 on a phone.** `com.uber:h3` carries its natives inside the jar as Java resources, and AGP drops `.so` files
from Java resources when it packages an APK. `app/build.gradle.kts` therefore copies `android-arm64` and
`android-arm` out of the jar into `arm64-v8a` / `armeabi-v7a` jniLibs (task `extractH3Natives`), and `AppGraph`
loads them with `H3Core.newSystemInstance()`. h3-java publishes no x86/x86_64 Android build, so **an x86_64
emulator image cannot run the H3 index**. Use an arm64 image or a device.

### Screen renders — `:app:renderScreens`

The app wears plan 10's **direction B**, the BioRig brand: deep-green ink, an emerald accent, hairline rules and
tabular monospace figures, light and dark. `BioRigTheme(darkTheme = isSystemInDarkTheme())` follows the phone and
lets a caller pin a mode. Each screen in `ui/Screens.kt` draws from plain state (a `WizardState`, a list of
`CaptureEntity`, a `ChainView`) and reports through callbacks. `ui/Routes.kt` connects the screens to
`WizardViewModel`, and the photo screen takes its camera as a slot.

That is what makes them renderable without a device. This box has no KVM, so an emulator runs under TCG, never
settles and screencaps black. The screenshots are therefore drawn on the JVM by Robolectric's native graphics,
from the real composables:

```bash
cd mobile/android && ANDROID_HOME=/opt/android-sdk ./gradlew :app:renderScreens --console=plain
```

It writes `screenshots/<screen>-<mode>.png` for setup, fix, photos, submit, queue and tree in light and dark, 12
files. The device spec is fixed: 360 x 780 dp at xxhdpi (density 3.0, 480 dpi), so every file is 1080 x 2340 px.
It also writes `screenshots/manifest.json` with the screen, mode, path, width, height and sha256 of each render,
plus the device spec. The states are fixed in `ScreenRenders.kt`: no clock, no random id, and the timezone pinned
to UTC. Two consecutive runs produce byte-identical PNGs and manifest. The task always re-renders and is never
served from the build cache. `tools/check_screenshots.py` (step 9 of `scripts/verify-demo.sh`) fails when a
committed PNG disagrees with the manifest, when a screen/mode is missing, or when a listed file is absent. Commit
the PNGs and the manifest together.

`compose.onRoot().captureToImage()` is not used. Under Robolectric it waits for a frame-commit callback that never
arrives, so it times out in either render mode. Instead the task lays the window out under Robolectric and draws
its decor view onto a Skia canvas.

## Known limits under contract v1

- **The offline queue has a 10-minute window.** The relay refuses a fix older than `FIX_MAX_AGE_S` (600 s) when it
  arrives. A tree captured with no signal must reach the relay within ten minutes of its fix. Otherwise the queue
  does not send it (that would be refused, and would count against the IP limit). It asks the planter to go back
  to the tree for a new fix, keeping the photo, the diameter and the submission id. Re-dating an old fix would be
  lying about it, so the app does not.
- **The pre-check cannot give a distance to someone else's tree.** `GET /v1/plots/{cell}` returns counts
  (`active`, `full`, `neighbourhood_active`), never coordinates, which the contract treats as personal data. The
  phone measures in metres only against its own earlier captures. For other planters' trees it reports how many
  are in reach, and the relay makes the 20 m call at submission (`409 collision` with the distance).
- **Idempotency across sessions relies on `same_tree`.** `replayed` applies only to the same session and
  `submission_id`. The queue keeps its session while it is valid. After a new session, a capture that already
  reached the relay comes back as `same_tree`: the same planter within 20 m.
- Photo-derived trunk measurement is out of scope. Biomass comes from the diameter the planter enters.

## What was and was not run where this was built

The machine has four cores, about 1 GB of free memory and no emulator.

- Run: `./gradlew :core:test` (43 tests), `gen_golden.py --check`, `check_registration_body.py`, `relay_e2e.py`,
  and `ANDROID_HOME=... ./gradlew :app:assembleDebug :app:compileDebugAndroidTestKotlin`. The debug APK assembled,
  with `lib/arm64-v8a/libh3-java.so` and `lib/armeabi-v7a/libh3-java.so` inside.
- Not run: `app/src/androidTest` (`CaptureDaoTest`, `FixScreenTest`). They compile, but nothing executed them;
  each file says so in its header. No screen was photographed, and nothing ran on a device (the screenshots are
  JVM renders of the composables, `:app:renderScreens` above). That includes the
  location, camera, Room, `H3Core.newSystemInstance()` and the chain read-back.
