#!/usr/bin/env bash
# Verify both demo pieces end to end. Exits non-zero on the first failure.
#   scripts/verify-demo.sh              full run (re-renders the 1080p master, ~80 s)
#   SKIP_RENDER=1 scripts/verify-demo.sh  probe the existing mp4 instead of re-rendering
#   VERIFY_ALLOW_NO_KEY=1 scripts/verify-demo.sh  key-free mode: a partial run, for CI and clean-clone proofs
#
# Key-free mode skips the steps that need the deployer key (3, the live mint simulation; 4-sim, the dashboard's
# simulation verdicts, replaced by its read-only state; 4b, the fork rehearsals; 6, the exact-key scan of tracked
# files, replaced by a pattern scan) and prints `SKIPPED (no key): step N` for
# each. Its closing banner names the skipped steps instead of ALL DEMO CHECKS PASSED, so a partial run can never
# read as a full acceptance pass. The flag is refused when a key IS configured: it cannot weaken a real run.
#
# Step 4b rehearses the two Celo mainnet operations that have already executed, against a fork of the live chain
# (script/safe-owner-swap-fork-check.sh then script/handover-fork-check.sh). It signs as the deployer and forks
# the chain, so it needs the key step 6 looks for and the live RPC, and it costs ~30 s. FORK_MODE is inherited,
# so FORK_MODE=pin (needs an archive FORK_URL) and FORK_MODE=raw (fails by design) reach both harnesses
# unchanged. Each rehearsal leaves its full log in cache/verify-demo/.
set -euo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python
MP4=assets/media/demo_90s.mp4
PORT=${DEMO_PORT:-8599}
step() { printf '\n== %s\n' "$*"; }
SKIPPED=()  # steps key-free mode did not run; named in the closing banner
skip() { echo "SKIPPED (no key): step $1"; SKIPPED+=("$1"); }

# Whether a key is configured, through the same loader steps 3, 4b and 6 use (.env, then the environment).
HAVE_KEY=$($PY -c 'from dashboard.config import load_settings; print(1 if (load_settings().private_key or "").strip() else 0)')
NO_KEY=0
if [ "${VERIFY_ALLOW_NO_KEY:-0}" = 1 ]; then
    if [ "$HAVE_KEY" = 1 ]; then
        echo "VERIFY_ALLOW_NO_KEY=1 refused: a PRIVATE_KEY is configured, so run the full gate instead"
        exit 1
    fi
    NO_KEY=1
    echo "key-free mode: steps 3, 4-sim, 4b and 6 will be SKIPPED; this is a partial run, not a full acceptance pass"
elif [ "${VERIFY_ALLOW_NO_KEY:-0}" != 0 ]; then
    echo "VERIFY_ALLOW_NO_KEY must be 1 or unset"; exit 1
fi

step "1. contract sources untouched (src/ and test/ match HEAD)"
git diff --quiet HEAD -- src test || { echo "src/ or test/ has local changes"; exit 1; }
echo "clean"

step "2. unit tests (dashboard pure logic + video timing + relay)"
out=$($PY -m pytest -q dashboard tools relay 2>&1) || { echo "$out"; exit 1; }
echo "$out" | tail -2
passed=$(echo "$out" | grep -oE '[0-9]+ passed' | grep -oE '[0-9]+')
[ "${passed:-0}" -gt 0 ] || { echo "no tests ran"; exit 1; }

step "3. live chain: getTreeStats, TBA derivation, mintTree eth_call simulation (no broadcast)"
if [ "$NO_KEY" = 1 ]; then skip 3; else $PY -m dashboard.smoke --token 1; fi

step "4. dashboard in a real browser"
# The pip package does not ship the browser binary, so a fresh machine fails the check below with
# "Executable doesn't exist" rather than a real UI fault. Bootstrap it once; a no-op when present.
$PY -m playwright install chromium >/dev/null 2>&1 || { echo "could not install playwright chromium"; exit 1; }
$PY -m streamlit run dashboard/app.py --server.headless true --server.port "$PORT" \
  --browser.gatherUsageStats false > .streamlit-run.log 2>&1 &
ST_PID=$!
KEYDIR=   # step 4b's key file; removed on the way out
trap 'kill "$ST_PID" 2>/dev/null || true; if [ -n "$KEYDIR" ]; then rm -rf "$KEYDIR"; fi' EXIT
for _ in $(seq 1 60); do curl -sf "localhost:$PORT/_stcore/health" >/dev/null && break; sleep 0.5; done
curl -sf "localhost:$PORT/_stcore/health" >/dev/null || { echo "streamlit did not start"; cat .streamlit-run.log; exit 1; }
hdrs=$(curl -sI "localhost:$PORT/")
if echo "$hdrs" | grep -qiE '^x-frame-options|frame-ancestors'; then echo "framing header present"; exit 1; fi
echo "no X-Frame-Options / frame-ancestors"
# Key-free, the dashboard is read-only by design: the UI check asserts that state in place of the simulation verdicts.
if [ "$NO_KEY" = 1 ]; then skip 4-sim; echo "  (step 4's simulation verdicts; the read-only state is checked instead)"; fi
$PY scripts/check_dashboard_ui.py "http://localhost:$PORT"
kill $ST_PID 2>/dev/null || true

step "4b. mainnet rehearsals on a fork: the Safe owner swap, then the role handover"
# Both operations EXECUTED on Celo mainnet on 1 October 2026 (swap tx 0x7a99f809…, block 78991457, then the
# mode-B handover, blocks 78991473-78991482). Nothing ran either harness afterwards, so both sat asserting the
# pre-operation world while forking the tip and neither red run was noticed. The gate runs them now: a rehearsal
# that cannot build its fork, or whose facts have moved, fails the gate instead of ageing quietly. ~30 s.
if [ "$NO_KEY" = 1 ]; then skip 4b; else
LOGDIR=cache/verify-demo; mkdir -p "$LOGDIR"
KEYDIR=$(mktemp -d); chmod 700 "$KEYDIR"
$PY - "$KEYDIR/deployer.key" <<'PY'
import pathlib, sys
from dashboard.config import load_settings
# Both rehearsals need the real deployer key as their local sender (the swap guard refuses any other signer).
# Nothing it signs reaches the chain: anvil forks the chain and every --broadcast goes to the fork.
key = (load_settings().private_key or "").strip()
if not key:
    sys.exit("no PRIVATE_KEY configured: the fork rehearsals sign as the deployer")
pathlib.Path(sys.argv[1]).write_text(key + "\n")
PY
chmod 600 "$KEYDIR/deployer.key"

rehearse() {  # $1 the harness: its verdict on success, its whole log on failure
    local log rc
    log="$LOGDIR/$(basename "$1").log"
    rc=0
    # Through bash, the way DEPLOY.md documents running them: the gate must test the rehearsal, not the
    # harness's file mode. A lost exec bit exits 126 and would read as a dead rehearsal.
    KEY_FILE="$KEYDIR/deployer.key" bash "$1" > "$log" 2>&1 || rc=$?
    if [ "$rc" -eq 0 ]; then
        grep -E '^REHEARSAL PASSED' "$log" | sed 's/^/  /' || true
        echo "  $(grep -cE '^  PASS ' "$log") checks passed, full log in $log"
        return 0
    fi
    echo "$(basename "$1") exited $rc"
    if [ "$rc" -eq 2 ]; then
        echo "  an environment gap, not a facts mismatch: it could not build its fork, so it asserted nothing"
    fi
    cat "$log"
    return 1
}

rehearse script/safe-owner-swap-fork-check.sh || exit 1
rehearse script/handover-fork-check.sh || exit 1
fi

step "5. video: render and probe"
if [ "${SKIP_RENDER:-0}" != 1 ]; then $PY tools/generate_demo.py --out "$MP4"; fi
[ -s "$MP4" ] || { echo "$MP4 missing"; exit 1; }
probe=$(ffprobe -v error -select_streams v:0 -count_frames \
  -show_entries stream=width,height,r_frame_rate,nb_read_frames -show_entries format=duration \
  -of default=nw=1 "$MP4")
echo "$probe"
echo "size=$(stat -c %s "$MP4") bytes"
echo "$probe" | grep -qx 'width=1920'        || { echo "width is not 1920"; exit 1; }
echo "$probe" | grep -qx 'height=1080'       || { echo "height is not 1080"; exit 1; }
echo "$probe" | grep -qx 'r_frame_rate=30/1' || { echo "fps is not 30"; exit 1; }
echo "$probe" | grep -qx 'nb_read_frames=2700' || { echo "frame count is not 2700"; exit 1; }
echo "$probe" | grep -qx 'duration=90.000000'  || { echo "duration is not 90.000000"; exit 1; }

step "5b. the roadmap label is in the rendered pixels, not only in the source"
$PY - "$MP4" <<'PY'
import sys
import cv2
import numpy as np

cap = cv2.VideoCapture(sys.argv[1])
WARN_BGR = np.array((36, 191, 251))  # demo_style.WARN (251, 191, 36), reversed for OpenCV


def warn_pixels(t):
    cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
    ok, frame = cap.read()
    if not ok:
        sys.exit(f"could not read a frame at t={t}")
    strip = frame[455:525, 95:520]  # the solid ROADMAP pill, scene 4
    return int((np.abs(strip.astype(int) - WARN_BGR).sum(axis=2) < 120).sum())


before, on_screen, closing = warn_pixels(71.0), warn_pixels(76.0), warn_pixels(89.0)
print(f"ROADMAP pill pixels: t=71 {before}, t=76 {on_screen}, closing card t=89 {closing}")
if before != 0:
    sys.exit("the 20% split was labelled as roadmap before its cue")
if on_screen < 2000:
    sys.exit("the roadmap pill is not on screen in scene 4 after its cue")
if closing <= 0:
    sys.exit("the roadmap line is missing from the closing card")
print("label burned into scene 4 and the closing card")
PY

step "6. secrets: the .env key is in no tracked file"
if [ "$NO_KEY" = 1 ]; then
    skip 6
    # Without the key there is nothing exact to look for; still refuse an assignment of key-shaped material. The
    # public anvil test keys (script/fork-dry-run.sh, marked "anvil" on their line) are not secrets.
    hits=$(git grep -nIE '(PRIVATE_KEY|private_key)[[:space:]]*[:=][[:space:]]*["'"'"']?(0x)?[0-9a-fA-F]{64}' -- . ':!lib' \
        | grep -vi anvil || true)
    if [ -n "$hits" ]; then echo "key-shaped assignment in tracked files:"; echo "$hits" | cut -d: -f1-2; exit 1; fi
    echo "  pattern scan only: no PRIVATE_KEY=<64 hex> assignment in tracked files"
else
$PY - <<'PY'
import subprocess, sys
from dashboard.config import load_settings
key = (load_settings().private_key or "").lower().removeprefix("0x")
if not key:
    sys.exit("no PRIVATE_KEY configured")
import os
files = [f for f in subprocess.check_output(["git", "ls-files", "-z"], text=True).split("\0") if os.path.isfile(f)]
hits = [f for f in files if key in open(f, "rb").read().decode("latin-1").lower()]
if hits:
    sys.exit(f"key found in tracked files: {hits}")
print(f"checked {len(files)} tracked files: none contain the key")
PY
fi

step "7. proposal carriers: the published copies still match their source"
# The thirteen files held in the workspace Files (the proposal pdf, docx and md, the architecture raster, its vector
# copy and the slide-size raster, the reviewers' debug apk, the milestone report, the deployment plan, FINDINGS.md,
# the two demo videos and the contract source doc) are compared against the markdown, the renderers, the committed
# diagram, the app source, the scenes and the contract they derive from (docs/carriers.json is the publish record).
# On 2 October 2026 the markdown had moved three commits past the published render and the Files raster was a
# pre-brand copy, and nothing noticed. The apk is pinned to the git tree of mobile/android it was built from rather
# than rebuilt, which needs no Android SDK here, and the slide raster to the provenance its own bytes carry rather
# than to pixels. Offline; re-renders the pdf with the Chromium step 4 installed. Copies staged under
# cache/carriers/published/ are checked too; without them it notes so and still fails on repo-side drift.
#
# The record is held to a floor of thirteen carriers, counted by distinct name. Losing a row used to be survivable:
# the tool reports on the carriers its own list names, so a record trimmed alongside that list still read clean, and
# two rows sharing a name collapse to one when the tool builds its index. The floor lives here so the gate keeps
# asserting it whatever the tool does. Adding a carrier means raising the number; lowering it means dropping a
# published carrier from the record, which is a decision, not a fix (DEPLOY.md section 9).
$PY - <<'PY' || { echo "the carrier record is short: see above, then DEPLOY.md section 9"; exit 1; }
import json, sys
from pathlib import Path

FLOOR = 13  # carriers the record must never hold fewer of; raise this when a carrier is added

try:
    rows = json.loads(Path("docs/carriers.json").read_text())["carriers"]
    names = [row["name"] for row in rows]
except (OSError, ValueError, KeyError, TypeError) as exc:
    sys.exit(f"docs/carriers.json could not be read as a carriers record ({exc!r})")

twice = sorted({name for name in names if names.count(name) > 1})
if twice:
    sys.exit(f"docs/carriers.json names {', '.join(twice)} more than once: "
             f"{len(names)} rows but only {len(set(names))} carriers")
if len(set(names)) < FLOOR:
    sys.exit(f"docs/carriers.json holds {len(set(names))} carriers, fewer than the {FLOOR} this gate requires; "
             f"a published carrier was dropped from the record")
print(f"carrier record holds {len(set(names))} carriers (floor {FLOOR})")
PY
$PY tools/check_carriers.py || { echo "carriers drifted: see DEPLOY.md section 9"; exit 1; }

step "8. documentation: every path, link, command, port and env var the docs name is real"
$PY tools/check_docs_paths.py || { echo "the docs name something that does not exist: see the findings above"; exit 1; }

if [ "${#SKIPPED[@]}" -gt 0 ]; then
    printf '\nPARTIAL: DEMO CHECKS PASSED EXCEPT SKIPPED STEPS: %s (key-free mode, not a full acceptance pass)\n' \
        "${SKIPPED[*]}"
    exit 0
fi
printf '\nALL DEMO CHECKS PASSED\n'
