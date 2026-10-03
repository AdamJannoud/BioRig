#!/usr/bin/env bash
# Shared fast-forward pre-flight: does the commit about to be pushed build on the remote's main?
#
# Sourced by both push paths so their verdicts cannot drift apart:
#   scripts/push-verified.sh  stage 0, which reads the remote itself with `git ls-remote`
#   scripts/git-hooks/pre-push  which git hands the remote sha on stdin, before any object is transferred
#
# Callers own the consequence (a refusal, or a loud override); this file only decides and explains.

# fast_forward_state <remote_sha> <local_sha> -> create | current | fast-forward | stale
#   create        the remote has no main yet: the push creates it
#   current       the remote's main is already this commit
#   fast-forward  the remote's main is an ancestor of this commit: the push advances the branch
#   stale         it does not build on the remote's main, so the push cannot land. Includes a remote sha that is not
#                 in this checkout at all: a commit's ancestors are always present locally, so an absent remote sha
#                 cannot be one of them, and the push is stale either way.
fast_forward_state() {
    local remote_sha=${1:-} local_sha=${2:?fast_forward_state needs a local sha}
    if [ -z "$remote_sha" ]; then
        echo create
    elif [ "$remote_sha" = "$local_sha" ]; then
        echo current
    elif git cat-file -e "${remote_sha}^{commit}" 2>/dev/null &&
        git merge-base --is-ancestor "$remote_sha" "$local_sha"; then
        echo fast-forward
    else
        echo stale
    fi
}

# fast_forward_report <label> <remote_sha> <local_sha> [remote]
#   Writes the diagnosis for a stale verdict: what the remote holds that this checkout does not, and the command that
#   fixes it. <label> names the remote as the reader knows it ("origin"); <remote> is what git can fetch from, and
#   defaults to the label.
fast_forward_report() {
    local label=${1:?} remote_sha=${2:?} local_sha=${3:?} remote=${4:-$1}
    local ahead
    echo "$label main is $remote_sha; $local_sha does not build on it: a stale base, not a remote problem."
    if git cat-file -e "${remote_sha}^{commit}" 2>/dev/null; then
        ahead=$(git rev-list --count "$local_sha..$remote_sha")
        echo "$label main has $ahead commit(s) this checkout does not:"
        git --no-pager log --format='    %h %s' --no-decorate "$local_sha..$remote_sha"
    else
        echo "$label main's tip is not in this checkout at all: it has never been fetched here."
    fi
    echo "rebase this checkout onto it and push again:"
    echo "    git fetch $remote && git rebase refs/remotes/$remote/main"
    echo "do not force-push: it would drop the work $label main already has."
}
