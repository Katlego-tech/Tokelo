#!/usr/bin/env bash
# keys.sh -- the project's release-signing key pair (DESIGN.md §3 row 10), made once; and on the
# cpanel platform, the deploy key and the host's pinned key (§15.4).
#
#   bash scripts/realm/keys.sh           the signing key pair
#   bash scripts/realm/keys.sh cpanel    the deploy key, and the host key, for the workflows
#
# cosign makes the pair in a temporary folder with a random password. The private key and the
# password go straight into the GitHub repo's secrets (COSIGN_PRIVATE_KEY, COSIGN_PASSWORD) with
# gh, and the temporary folder is deleted: the private half never rests in the repo or on disk.
# Only cosign.pub stays, at the repo root; commit it. To rotate, delete cosign.pub and run again.
#
# keys.sh cpanel makes an ed25519 deploy key the same way: its private half goes into the secret
# CPANEL_SSH_KEY and is deleted here; its public half is printed, to authorise in cPanel. It
# asks the host for its key (ssh-keyscan) and pins it in CPANEL_KNOWN_HOSTS, after checking it
# against the key this machine already trusts for the host, when there is one. And it sets the
# variables CPANEL_SSH_HOSTNAME, CPANEL_SSH_PORT and CPANEL_SSH_USER from this machine's entry
# for [deploy] ssh_host (ssh -G), so the workflows reach the host the way you do. Run it again
# to rotate the deploy key, then remove the old one in cPanel.

set -euo pipefail
die() { printf '!! keys: %s\n' "$*" >&2; exit 1; }
case "${1:-}" in
  "") mode=cosign ;;
  cpanel) mode=cpanel ;;
  *) printf 'usage: keys.sh [cpanel]\n' >&2; exit 2 ;;
esac
root="$(git rev-parse --show-toplevel)"
cd "$root"

# In the kit's own folder it would put signing secrets on the kit's repo (§14.8).
[ -f realm.toml ] || die "no realm.toml at the repo root: run this in a Secret Realm project, not the kit"
if [ "$mode" = cosign ]; then
  [ ! -f cosign.pub ] || die "cosign.pub exists: delete it first to rotate the key pair"
else
  [ "$(scripts/realm/realm release config deploy.platform 2>/dev/null)" = cpanel ] \
    || die 'keys.sh cpanel is for a project with [deploy] platform = "cpanel"'
fi
command -v gh >/dev/null || die "gh isn't installed: it puts the private key into the repo's secrets"
gh auth status >/dev/null 2>&1 || die "gh isn't logged in: gh auth login"
url="$(git remote get-url origin 2>/dev/null)" || die "no origin remote: create the GitHub repo and push first"
repo="$(printf '%s' "$url" | sed -E 's#^(git@github\.com:|https://github\.com/)##; s#\.git$##')"
[[ "$repo" =~ ^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$ ]] || die "origin isn't a GitHub repo: $url"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

if [ "$mode" = cpanel ]; then
  host="$(scripts/realm/realm release config deploy.ssh_host)" || die "realm.toml [deploy] has no ssh_host"
  ssh_config=()
  [ -n "${REALM_SSH_CONFIG:-}" ] && ssh_config=(-F "$REALM_SSH_CONFIG")
  resolved="$(ssh "${ssh_config[@]}" -G "$host")" || die "ssh couldn't read your entry for $host"
  hostname="$(sed -n 's/^hostname //p' <<<"$resolved")"
  port="$(sed -n 's/^port //p' <<<"$resolved")"
  user="$(sed -n 's/^user //p' <<<"$resolved")"
  name="$hostname"; [ "$port" = 22 ] || name="[$hostname]:$port"

  ssh-keyscan -p "$port" -t ed25519,ecdsa,rsa "$hostname" 2>/dev/null | grep -v '^#' > "$tmp/known_hosts" || true
  [ -s "$tmp/known_hosts" ] || die "$hostname:$port didn't answer ssh-keyscan: is the host or port right?"
  # The key it offers now, against the one this machine trusts already (if it has connected).
  trusted=""
  for file in $(sed -n 's/^userknownhostsfile //p' <<<"$resolved"); do
    file="${file/#\~/$HOME}"
    [ -f "$file" ] && trusted+="$(ssh-keygen -F "$name" -f "$file" 2>/dev/null | grep -v '^#' || true)"$'\n'
  done
  if grep -q '[^[:space:]]' <<<"$trusted"; then
    match=no
    while read -r _ kind blob _; do
      [ -n "${blob:-}" ] && grep -qF " $kind $blob" <<<"$trusted" && match=yes
    done < "$tmp/known_hosts"
    [ "$match" = yes ] || die "the key $name offers now isn't the key this machine already trusts for $name: don't pin it until you know why"
    echo "The host key matches the one this machine already trusts for $name."
  else
    echo "Not checked against a known host key: this machine has none for $name. Check these"
    echo "fingerprints by eye against your host's (cPanel shows them under SSH Access, or ask):"
    ssh-keygen -lf "$tmp/known_hosts" | sed 's/^/   /'
  fi

  ssh-keygen -q -t ed25519 -N '' -C "realm-deploy $repo" -f "$tmp/deploy" || die "ssh-keygen couldn't make the deploy key"
  gh secret set CPANEL_SSH_KEY --repo "$repo" < "$tmp/deploy" >/dev/null \
    || die "couldn't set CPANEL_SSH_KEY on $repo"
  gh secret set CPANEL_KNOWN_HOSTS --repo "$repo" < "$tmp/known_hosts" >/dev/null \
    || die "couldn't set CPANEL_KNOWN_HOSTS on $repo"
  for pair in "CPANEL_SSH_HOSTNAME=$hostname" "CPANEL_SSH_PORT=$port" "CPANEL_SSH_USER=$user"; do
    gh variable set "${pair%%=*}" --repo "$repo" --body "${pair#*=}" >/dev/null \
      || die "couldn't set the variable ${pair%%=*} on $repo"
  done
  echo
  echo "CPANEL_SSH_KEY and CPANEL_KNOWN_HOSTS are set on $repo, with the variables for $user@$name;"
  echo "the private key is gone from this machine. Now authorise the public half in cPanel:"
  echo "SSH Access -> Manage SSH Keys -> Import Key (paste it as the public key), then Authorize."
  echo
  cat "$tmp/deploy.pub"
  exit 0
fi

cosign="$(bash scripts/realm/tools.sh cosign)"
# The key's passphrase: 32 random bytes, as letters, digits, - and _. Not from python3: where
# that's missing or too old, the realm tools run through uv, and this stopped without a word.
phrase="$(head -c 32 /dev/urandom | base64 | tr -d '=\n' | tr '+/' '-_')"
[ "${#phrase}" -ge 43 ] || die "couldn't make a passphrase for the key (head, base64 and /dev/urandom are needed)"
(cd "$tmp" && COSIGN_PASSWORD="$phrase" "$cosign" generate-key-pair >/dev/null 2>&1) \
  || die "cosign couldn't make the key pair"
gh secret set COSIGN_PRIVATE_KEY --repo "$repo" < "$tmp/cosign.key" >/dev/null \
  || die "couldn't set COSIGN_PRIVATE_KEY on $repo"
printf '%s' "$phrase" | gh secret set COSIGN_PASSWORD --repo "$repo" >/dev/null \
  || die "couldn't set COSIGN_PASSWORD on $repo"
cp "$tmp/cosign.pub" cosign.pub
echo "COSIGN_PRIVATE_KEY and COSIGN_PASSWORD are set on $repo; the private key is gone from this machine."
echo "Commit cosign.pub: git add cosign.pub && git commit -m 'build: T000 the release-signing public key'"
