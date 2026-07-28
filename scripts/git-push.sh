#!/usr/bin/env bash
#
# git-push.sh — push the current branch to origin without ever writing a token
# to disk or embedding one in the remote URL.
#
# Credentials are resolved in this order, first hit wins:
#   1. $GITHUB_PAT from the environment
#   2. GITHUB_PAT= in ~/.bashrc  (it is set there but not exported, so a
#      non-interactive shell never sees it)
#   3. gh's own OAuth token, via `gh auth git-credential`
#
# The token is passed to git through an ephemeral credential helper that reads
# it from the environment. It is never placed on the command line (which `ps`
# would expose), never written to ~/.git-credentials, and never added to the
# remote URL. Nothing this script does persists after it exits.
#
# Usage:
#   scripts/git-push.sh                 # push the current branch to origin
#   scripts/git-push.sh main            # push a named branch
#   scripts/git-push.sh --dry-run       # show what would be pushed
#   scripts/git-push.sh main --force-with-lease
#
# Any extra arguments are forwarded to `git push` unchanged.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

# Redact anything that looks like a credential before it reaches the terminal.
# git occasionally echoes the remote URL, and a misconfigured remote may still
# carry user:token@host.
redact() {
    sed -E 's#://[^@/]*@#://<credentials>@#g; s/gh[pousr]_[A-Za-z0-9]{20,}/<token>/g'
}

die() { echo "❌ $*" >&2; exit 1; }

git rev-parse --git-dir >/dev/null 2>&1 || die "not inside a git repository"

BRANCH=""
if [[ $# -gt 0 && "$1" != -* ]]; then
    BRANCH="$1"
    shift
else
    BRANCH="$(git symbolic-ref --quiet --short HEAD)" \
        || die "detached HEAD — pass a branch name explicitly"
fi

# Refuse to push a dirty tree silently. Uncommitted work is almost never meant
# to be left behind, and finding out after the fact is worse than being told.
if [[ -n "$(git status --porcelain)" ]]; then
    echo "⚠️  Working tree is not clean; these changes will NOT be pushed:"
    git status --short
    echo
fi

# Resolve the token without printing it.
if [[ -z "${GITHUB_PAT:-}" && -f "$HOME/.bashrc" ]]; then
    # Assignment only — never source ~/.bashrc, which would run arbitrary
    # startup code as a side effect of pushing.
    GITHUB_PAT="$(sed -nE 's/^[[:space:]]*(export[[:space:]]+)?GITHUB_PAT=["'"'"']?([^"'"'"']+)["'"'"']?.*/\2/p' \
        "$HOME/.bashrc" | head -1)"
fi

declare -a CRED_ARGS=()
if [[ -n "${GITHUB_PAT:-}" ]]; then
    export GITHUB_PAT
    AUTH_SOURCE="GITHUB_PAT"
    # The helper body names the variable; git runs it with our environment, so
    # the value itself never appears in the process arguments.
    HELPER='!f() { echo username=x-access-token; echo "password=$GITHUB_PAT"; }; f'
elif gh auth status >/dev/null 2>&1; then
    AUTH_SOURCE="gh (OAuth token)"
    HELPER='!gh auth git-credential'
else
    die "no credentials: set GITHUB_PAT or run 'gh auth login'"
fi

# The empty value first CLEARS any inherited helper list. Without it a
# host-specific helper in ~/.gitconfig (e.g. 'store') wins over ours and the
# push fails with a stale token — the exact failure this script exists to avoid.
CRED_ARGS=(
    -c "credential.https://github.com.helper="
    -c "credential.https://github.com.helper=$HELPER"
)

# A dry run contacts the remote and authenticates but changes nothing, so the
# closing message must not claim otherwise.
DRY_RUN=0
for arg in "$@"; do
    [[ "$arg" == "--dry-run" || "$arg" == "-n" ]] && DRY_RUN=1
done

echo "🔐 Auth: $AUTH_SOURCE"
echo "🚀 $([[ $DRY_RUN -eq 1 ]] && echo "Dry run:" || echo "Pushing") $BRANCH → origin"

set +e
git "${CRED_ARGS[@]}" push origin "$BRANCH" "$@" 2>&1 | redact
STATUS=${PIPESTATUS[0]}
set -e

if [[ $STATUS -ne 0 ]]; then
    die "push failed (exit $STATUS)"
fi

if [[ $DRY_RUN -eq 1 ]]; then
    echo "✅ Dry run OK — authenticated, nothing pushed."
else
    echo "✅ Pushed. local=$(git rev-parse --short HEAD) origin/$BRANCH=$(git rev-parse --short "origin/$BRANCH" 2>/dev/null || echo '?')"
fi
