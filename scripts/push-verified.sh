#!/usr/bin/env bash
# The way to push BioRig's main: check the push can land, prove the commit, push it, then prove what landed.
#   scripts/push-verified.sh            push HEAD to origin's main
#   scripts/push-verified.sh <remote>   another remote
#
# 0. A pre-flight on the remote's main, before anything expensive: a local commit that is not a fast-forward of it is a
#    stale base, and the push is rejected "fetch first" only after the whole proof below has run. Caught here in
#    seconds, naming the remote sha and the rebase to run. The remote is read directly (git ls-remote), never a
#    tracking ref, which may itself be stale. The check itself is scripts/lib/fast_forward_check.sh, the same one the
#    pre-push hook runs, so a plain `git push` gives the same verdict with the same numbers.
# 1. tools/clean_clone_proof.py --source local proves HEAD from a plain clone of this checkout: the README quick
#    start line by line, then the whole acceptance gate with the deployer key. Anything short of PASS stops here.
# 2. git push <remote> HEAD:refs/heads/main. The pre-push hook (tools/install_git_hooks.py) finds the PASS record
#    stage 1 wrote for this exact commit and tree and does not prove it a second time.
# 3. git ls-remote must report the local sha as the remote's main, and a --source github proof clones the pushed
#    tip back from the remote and runs everything again: what landed is what was proven.
# Exits nonzero naming the stage that failed. The deployer key is read where it already lives (PRIVATE_KEY, or the
# checkout's gitignored .env); it never leaves this machine.
set -euo pipefail
cd "$(dirname "$0")/.."
remote=${1:-origin}
sha=$(git rev-parse HEAD)
url=$(git remote get-url "$remote")
records="$(git rev-parse --path-format=absolute --git-common-dir)/clean-clone-proof"
mkdir -p "$records"
fail() { echo; echo "push-verified: FAILED at stage $1"; exit 1; }
# shellcheck source=scripts/lib/fast_forward_check.sh
. scripts/lib/fast_forward_check.sh

if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
    echo "push-verified: the working tree has uncommitted changes; the proof covers $sha only, which is what is pushed"
fi

echo "== stage 0/3: pre-flight on $remote main"
remote_sha=$(git ls-remote "$remote" refs/heads/main | cut -f1) || fail "0 (pre-flight: cannot read $remote main)"
state=$(fast_forward_state "$remote_sha" "$sha")
if [ "$state" = create ]; then
    echo "pre-flight: $remote has no main yet; the push creates it"
elif [ "$state" = current ]; then
    echo "pre-flight: $remote main is already $sha"
else
    # Fetch here even when the verdict looks settled: the remote's tip may not be in this checkout at all, and an
    # absent tip reads as stale. Only a fetched object settles the ancestry. The ls-remote above is what counts as the
    # remote's tip; a tracking ref is stale exactly in the case this pre-flight exists for.
    git fetch --quiet "$remote" "+refs/heads/main:refs/remotes/$remote/main" \
        || fail "0 (pre-flight: cannot fetch $remote main)"
    if [ "$(fast_forward_state "$remote_sha" "$sha")" = fast-forward ]; then
        echo "pre-flight: $remote main is behind $sha; the push fast-forwards it"
    else
        echo "pre-flight: the push would be rejected 'fetch first' - after the whole proof had run."
        fast_forward_report "$remote" "$remote_sha" "$sha" "$remote"
        fail "0 (pre-flight: $sha is not a fast-forward of $remote main)"
    fi
fi

echo "== stage 1/3: prove $sha from a clean clone of this checkout"
python3 tools/clean_clone_proof.py --source local --commit "$sha" --json "$records/$sha.json" || fail "1 (local proof)"

echo "== stage 2/3: push $sha to $remote main"
git push "$remote" "$sha:refs/heads/main" || fail "2 (push)"

echo "== stage 3/3: confirm what landed on $remote"
landed=$(git ls-remote "$url" refs/heads/main | cut -f1)
echo "local  $sha"
echo "remote $landed"
[ "$landed" = "$sha" ] || fail "3 (ls-remote: the remote's main is not the commit just pushed)"
python3 tools/clean_clone_proof.py --source github --remote-url "$url" --ref main --commit "$sha" \
    --json "$records/$sha.remote.json" || fail "3 (proof of the pushed tip)"

echo
echo "PUSH VERIFIED: $sha is $remote's main and passed the clean-clone proof before and after the push"
