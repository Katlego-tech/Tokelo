#!/usr/bin/env bash
# keys.sh -- the project's release-signing key pair (DESIGN.md §3 row 10), made once.
#
#   bash scripts/realm/keys.sh
#
# cosign makes the pair in a temporary folder with a random password. The private key and the
# password go straight into the GitHub repo's secrets (COSIGN_PRIVATE_KEY, COSIGN_PASSWORD) with
# gh, and the temporary folder is deleted: the private half never rests in the repo or on disk.
# Only cosign.pub stays, at the repo root; commit it. To rotate, delete cosign.pub and run again.

set -euo pipefail
root="$(git rev-parse --show-toplevel)"
cd "$root"
die() { printf '!! keys: %s\n' "$*" >&2; exit 1; }

# In the kit's own folder it would put signing secrets on the kit's repo (§14.8).
[ -f realm.toml ] || die "no realm.toml at the repo root: run this in a Secret Realm project, not the kit"
[ ! -f cosign.pub ] || die "cosign.pub exists: delete it first to rotate the key pair"
command -v gh >/dev/null || die "gh isn't installed: it puts the private key into the repo's secrets"
gh auth status >/dev/null 2>&1 || die "gh isn't logged in: gh auth login"
url="$(git remote get-url origin 2>/dev/null)" || die "no origin remote: create the GitHub repo and push first"
repo="$(printf '%s' "$url" | sed -E 's#^(git@github\.com:|https://github\.com/)##; s#\.git$##')"
[[ "$repo" =~ ^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$ ]] || die "origin isn't a GitHub repo: $url"

cosign="$(bash scripts/realm/tools.sh cosign)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
phrase="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"  # the key's passphrase
(cd "$tmp" && COSIGN_PASSWORD="$phrase" "$cosign" generate-key-pair >/dev/null 2>&1) \
  || die "cosign couldn't make the key pair"
gh secret set COSIGN_PRIVATE_KEY --repo "$repo" < "$tmp/cosign.key" >/dev/null \
  || die "couldn't set COSIGN_PRIVATE_KEY on $repo"
printf '%s' "$phrase" | gh secret set COSIGN_PASSWORD --repo "$repo" >/dev/null \
  || die "couldn't set COSIGN_PASSWORD on $repo"
cp "$tmp/cosign.pub" cosign.pub
echo "COSIGN_PRIVATE_KEY and COSIGN_PASSWORD are set on $repo; the private key is gone from this machine."
echo "Commit cosign.pub: git add cosign.pub && git commit -m 'build: T000 the release-signing public key'"
