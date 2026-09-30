#!/usr/bin/env bash
# Verify both demo pieces end to end. Exits non-zero on the first failure.
#   scripts/verify-demo.sh              full run (re-renders the 1080p master, ~80 s)
#   SKIP_RENDER=1 scripts/verify-demo.sh  probe the existing mp4 instead of re-rendering
set -euo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python
MP4=assets/media/demo_90s.mp4
PORT=${DEMO_PORT:-8599}
step() { printf '\n== %s\n' "$*"; }

step "1. contract sources untouched (src/ and test/ match HEAD)"
git diff --quiet HEAD -- src test || { echo "src/ or test/ has local changes"; exit 1; }
echo "clean"

step "2. unit tests (dashboard pure logic + video timing)"
out=$($PY -m pytest -q dashboard tools 2>&1) || { echo "$out"; exit 1; }
echo "$out" | tail -2
passed=$(echo "$out" | grep -oE '[0-9]+ passed' | grep -oE '[0-9]+')
[ "${passed:-0}" -gt 0 ] || { echo "no tests ran"; exit 1; }

step "3. live chain: getTreeStats, TBA derivation, mintTree eth_call simulation (no broadcast)"
$PY -m dashboard.smoke --token 1

step "4. dashboard in a real browser"
# The pip package does not ship the browser binary, so a fresh machine fails the check below with
# "Executable doesn't exist" rather than a real UI fault. Bootstrap it once; a no-op when present.
$PY -m playwright install chromium >/dev/null 2>&1 || { echo "could not install playwright chromium"; exit 1; }
$PY -m streamlit run dashboard/app.py --server.headless true --server.port "$PORT" \
  --browser.gatherUsageStats false > .streamlit-run.log 2>&1 &
ST_PID=$!
trap 'kill $ST_PID 2>/dev/null || true' EXIT
for _ in $(seq 1 60); do curl -sf "localhost:$PORT/_stcore/health" >/dev/null && break; sleep 0.5; done
curl -sf "localhost:$PORT/_stcore/health" >/dev/null || { echo "streamlit did not start"; cat .streamlit-run.log; exit 1; }
hdrs=$(curl -sI "localhost:$PORT/")
if echo "$hdrs" | grep -qiE '^x-frame-options|frame-ancestors'; then echo "framing header present"; exit 1; fi
echo "no X-Frame-Options / frame-ancestors"
$PY scripts/check_dashboard_ui.py "http://localhost:$PORT"
kill $ST_PID 2>/dev/null || true

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

printf '\nALL DEMO CHECKS PASSED\n'
