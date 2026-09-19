#!/usr/bin/env bash
# aws-bootstrap.sh -- an AWS project's first step (DESIGN.md §14.5), run by you, signed in to
# your own account. It creates things that cost money, so nothing is created until you answer
# Terraform's "yes".
#
#   aws login --profile <profile> && export AWS_PROFILE=<profile>
#   TF_VAR_budget_email=<where the budget's alerts go> bash scripts/realm/aws-bootstrap.sh
#
# 0. Brings infra/bootstrap/terraform.tfvars in step: github_repository from the origin remote,
#    services from realm.toml's [[service]] names, github_subject_prefix from GitHub's API (the
#    start of the repo's OIDC subject: immutable, repo:OWNER@ID/REPO@ID, for newer repos).
# 1. Applies infra/bootstrap: the state bucket and its key, GitHub's OIDC provider, the four
#    roles, the permissions boundary, a repository per service, the budget. The first time, with
#    local state.
# 2. Writes backend.hcl in infra/bootstrap and in each infra/envs/* root.
# 3. The first time: moves the bootstrap's state into the bucket it has just created.
# 4. Sets the repository's variables through gh's REST API (any gh): AWS_REGION and the four
#    role ARNs.
# 5. Writes [deploy] registry into realm.toml.
#
# Then commit infra/bootstrap/terraform.tfvars, the backend.hcl files and realm.toml. After a failure, run it again: the local
# state is kept until it's in the bucket. Later, run it again to change the bootstrap, such as
# a repository for a new service in infra/bootstrap/terraform.tfvars.

set -euo pipefail
root="$(git rev-parse --show-toplevel)"
cd "$root"
realm="$root/scripts/realm/realm"
say() { printf '%s\n' "$*"; }
step() { printf '\n-> %s\n' "$*"; }
die() { printf '!! aws-bootstrap: %s\n' "$*" >&2; exit 1; }

[ -f realm.toml ] || die "no realm.toml at the repo root: run this in a Secret Realm project"
[ "$("$realm" release config deploy.platform)" = aws ] || die "realm.toml's [deploy] platform isn't aws"
[ -f infra/bootstrap/main.tf ] || die "no infra/bootstrap: setup-realm.sh --platform aws puts it there"
[ -f infra/bootstrap/terraform.tfvars ] || die "no infra/bootstrap/terraform.tfvars: setup-realm.sh writes it"
[ -n "${TF_VAR_budget_email:-}" ] \
  || die "set TF_VAR_budget_email: where the budget's alerts go (it's never written to a file)"
command -v aws >/dev/null || die "the AWS CLI v2 isn't installed"
command -v gh >/dev/null || die "gh isn't installed: it sets the repository's variables"
gh auth status >/dev/null 2>&1 || die "gh isn't logged in: gh auth login"
url="$(git remote get-url origin 2>/dev/null)" || die "no origin remote: create the GitHub repo and push first"
repo="$(printf '%s' "$url" | sed -E 's#^(git@github\.com:|https://github\.com/)##; s#\.git$##')"
[[ "$repo" =~ ^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$ ]] || die "origin isn't a GitHub repo: $url"
# The start of the repo's OIDC `sub` claim, which the roles trust, as GitHub itself reports it:
# repositories created after 2026-07-15 have immutable subjects, repo:OWNER@ID/REPO@ID.
prefix="$(gh api "repos/$repo/actions/oidc/customization/sub" --jq '.sub_claim_prefix // ""')" \
  || die "couldn't read $repo's OIDC subject from GitHub (repos/$repo/actions/oidc/customization/sub)"
[ -n "$prefix" ] || prefix="repo:$repo"
[[ "$prefix" =~ ^repo:[A-Za-z0-9._-]+(@[0-9]+)?/[A-Za-z0-9._-]+(@[0-9]+)?$ ]] \
  || die "GitHub's OIDC subject for $repo isn't one the bootstrap understands: $prefix"
region="$("$realm" release config deploy.region)" || die "realm.toml's [deploy] needs region"
terraform="$(bash scripts/realm/tools.sh terraform)" || die "couldn't fetch Terraform (above)"

# Terraform's AWS provider may not read an `aws login` profile, so it gets the CLI's current
# credentials instead, fresh before each call: they're short-lived. Keys already in the
# environment (yours) are used as they are.
exported=0
credentials() {
  if [ -n "${AWS_ACCESS_KEY_ID:-}" ] && [ "$exported" -eq 0 ]; then return 0; fi
  unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN AWS_CREDENTIAL_EXPIRATION
  local pairs line
  pairs="$(aws configure export-credentials --format env-no-export)" \
    || die "the AWS CLI isn't signed in: aws login --profile <profile>, then export AWS_PROFILE=<profile>"
  while IFS= read -r line; do
    case "${line%%=*}" in
      AWS_ACCESS_KEY_ID|AWS_SECRET_ACCESS_KEY|AWS_SESSION_TOKEN|AWS_CREDENTIAL_EXPIRATION)
        export "${line?}" ;;
    esac
  done <<<"$pairs"
  exported=1
}
tf() { credentials; TF_IN_AUTOMATION=1 CHECKPOINT_DISABLE=1 "$terraform" "$@"; }
value() {  # value <output> [key]: one of the bootstrap's outputs
  printf '%s' "$outputs" | python3 -c 'import json, sys
v = json.load(sys.stdin)[sys.argv[1]]["value"]
print(v[sys.argv[2]] if len(sys.argv) > 2 else v)' "$@"
}

names="$("$realm" release names)" || die "realm.toml's [[service]] names need fixing (above)"
[ -n "$names" ] || die "realm.toml has no [[service]]: the bootstrap makes an image repository for each"
python3 - "$repo" "$names" "$prefix" <<'PY' || die "couldn't bring infra/bootstrap/terraform.tfvars in step"
import json, re, sys
from pathlib import Path
path = Path("infra/bootstrap/terraform.tfvars")
text = path.read_text()
for key, value in (("github_repository", sys.argv[1]), ("services", sys.argv[2].split()),
                   ("github_subject_prefix", sys.argv[3])):
    text, n = re.subn(rf"^({key}\s*=\s*).*$", lambda m: m.group(1) + json.dumps(value), text,
                      count=1, flags=re.M)
    if n == 0 and key == "github_subject_prefix":  # projects set up before it existed
        text = text.rstrip("\n") + f"\n{key} = {json.dumps(value)}\n"
    elif n != 1:
        sys.exit(f"infra/bootstrap/terraform.tfvars has no {key} line")
# Aligned as `terraform fmt` aligns them, so the gate's format check stays clean: each run of
# `key = value` lines shares one column for its `=`.
lines, block = text.split("\n"), []
for i, line in enumerate(lines + [""]):
    if re.match(r"^[A-Za-z_][A-Za-z0-9_-]*\s*=", line):
        block.append(i)
        continue
    width = max((len(lines[j].split("=", 1)[0].strip()) for j in block), default=0)
    for j in block:
        key, rest = lines[j].split("=", 1)
        lines[j] = f"{key.strip():<{width}} = {rest.strip()}"
    block = []
path.write_text("\n".join(lines))
PY

credentials
account="$(aws sts get-caller-identity --query Account --output text)" \
  || die "the AWS CLI can't say which account it's signed in to"
say "== bootstrap $repo in AWS account $account, $region =="

# Applied before, with its state in the bucket: apply against that. Otherwise local state first.
dir=infra/bootstrap
first=1
[ -f "$dir/backend.hcl" ] && [ ! -f "$dir/terraform.tfstate" ] && first=0
override="$dir/backend_override.tf"
if [ "$first" -eq 1 ]; then
  step "1. the bootstrap, with local state (Terraform shows its plan and waits for your yes)"
  printf 'terraform {\n  backend "local" {}\n}\n' > "$override"
  trap 'rm -f "$override"' EXIT
  tf -chdir="$dir" init -input=false -reconfigure >/dev/null || die "terraform init failed"
else
  step "1. the bootstrap, against its state in the bucket (Terraform shows its plan and waits)"
  tf -chdir="$dir" init -input=false -reconfigure -backend-config=backend.hcl >/dev/null \
    || die "terraform init failed"
fi
tf -chdir="$dir" apply || die "the apply didn't finish; run this again to carry on"
outputs="$(tf -chdir="$dir" output -json)"
bucket="$(value state_bucket)"
key="$(value state_key)"
registry="$(value registry)"

step "2. backend.hcl in each root"
for root_dir in infra/bootstrap infra/envs/*; do
  [ -n "$(find "$root_dir" -maxdepth 1 -name '*.tf' -print -quit)" ] || continue
  cat > "$root_dir/backend.hcl" <<EOF
# Written by scripts/realm/aws-bootstrap.sh: where this root's state lives (DESIGN.md §14.5).
bucket       = "$bucket"
key          = "${root_dir#infra/}/terraform.tfstate"
region       = "$region"
encrypt      = true
kms_key_id   = "$key"
use_lockfile = true
EOF
  say "   $root_dir/backend.hcl"
done

if [ "$first" -eq 1 ]; then
  step "3. the bootstrap's state, into $bucket"
  rm -f "$override"
  tf -chdir="$dir" init -input=false -migrate-state -force-copy -backend-config=backend.hcl >/dev/null \
    || die "couldn't move the state into $bucket; the local copy is still in $dir"
  [ -n "$(tf -chdir="$dir" state list)" ] || die "the state in $bucket reads back empty"
  rm -f "$dir/terraform.tfstate" "$dir/terraform.tfstate.backup"
  say "   in s3://$bucket/bootstrap/terraform.tfstate; the local copy is gone"
fi

step "4. the repository's variables, on $repo"
# Through the REST API, which every gh has (`gh variable` needs gh 2.31 or later): update the
# variable if it's there, create it if it isn't.
setvar() {  # setvar NAME VALUE
  gh api -X PATCH "repos/$repo/actions/variables/$1" -f name="$1" -f value="$2" >/dev/null 2>&1 \
    || gh api -X POST "repos/$repo/actions/variables" -f name="$1" -f value="$2" >/dev/null \
    || die "couldn't set the variable $1 on $repo"
  say "   $1"
}
setvar AWS_REGION "$region"
for kind in plan apply release promote; do
  setvar "AWS_$(printf '%s' "$kind" | tr 'a-z' 'A-Z')_ROLE" "$(value roles "$kind")"
done

step "5. [deploy] registry in realm.toml"
python3 - "$registry" <<'PY'
import json, re, sys
from pathlib import Path
path = Path("realm.toml")
text, n = re.subn(r'^(registry = )"[^"\n]*"', lambda m: m.group(1) + json.dumps(sys.argv[1]),
                  path.read_text(), count=1, flags=re.M)
if n != 1:
    sys.exit("realm.toml has no registry line in [deploy]")
path.write_text(text)
PY
say "   registry = \"$registry\""

say ""
say "== bootstrapped. Next (docs/release/README.md, the aws platform):"
say "   1. commit infra/bootstrap/terraform.tfvars, infra/*/backend.hcl and realm.toml, through a PR"
say "   2. tag v0.0.0 on main and push the tag: the seed images"
say "   3. the infrastructure PR for staging; merging it applies staging"
