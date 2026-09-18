# scripts/realm/checks.sh -- Secret Realm's checks, run by scripts/gate.sh (one line there).
#
# Sourced, not executed: it uses the gate's own step/say/bad helpers and its fail and ran
# counters, so a realm check that fails, or can't run, fails the gate like any other check.
# That's Cultivation's skip rule, unchanged.
#
# The checks apply to Secret Realm projects: the ones with a realm.toml (DESIGN.md §8).

# Pinned, like the gate's other tools: uvx fetches exactly this version, never "latest".
SEMGREP_VERSION=1.177.0
SEMGREP_CONFIG=p/default   # the Semgrep registry's default rules: downloaded, so it needs network
CHECKOV_VERSION=3.3.17     # Terraform, tflint and tflint's AWS ruleset are pinned in tools.sh

realm_checks() {
  local realm="$root/scripts/realm/realm"

  if [ ! -f "$root/realm.toml" ]; then
    # A realm project that lost its marker would stop being checked without a word.
    if [ -f "$root/REQUIREMENTS.md" ]; then
      step "realm checks"
      bad "REQUIREMENTS.md is here but realm.toml isn't, so the realm checks can't tell this is"
      bad "   a Secret Realm project. Restore realm.toml (setup-realm.sh writes it)."
      fail=1
      ran=$((ran + 1))
    fi
    return 0
  fi

  step "realm: requirements (req-lint)"
  "$realm" req-lint || fail=1
  ran=$((ran + 1))

  step "realm: traceability (trace)"
  "$realm" trace || fail=1
  ran=$((ran + 1))

  step "realm: decision records (adr-check)"
  "$realm" adr-check || fail=1
  ran=$((ran + 1))

  step "realm: architecture and threats (design-check)"
  "$realm" design-check || fail=1
  ran=$((ran + 1))

  step "realm: stage gates (gates)"
  "$realm" gates || fail=1
  ran=$((ran + 1))

  step "realm: incidents (incidents)"
  "$realm" incidents || fail=1
  ran=$((ran + 1))

  step "realm: static security analysis (Semgrep $SEMGREP_VERSION, $SEMGREP_CONFIG)"
  if ! command -v uvx >/dev/null 2>&1; then
    bad "uvx (from uv) isn't on PATH, so Semgrep can't run. Install uv: https://docs.astral.sh/uv/"
    fail=1
  elif uvx --quiet --from "semgrep==$SEMGREP_VERSION" semgrep scan --config "$SEMGREP_CONFIG" \
         --error --metrics off --quiet --disable-version-check "$root"; then
    say "   clean"
  else
    bad "Semgrep found the issues above, or couldn't run (its rules need the network)."
    fail=1
  fi
  ran=$((ran + 1))

  realm_infra
}

# The Terraform checks (DESIGN.md §14.6), when infra/ holds .tf files: format, validity, a
# committed lock file per root, tflint with the AWS ruleset, and checkov with a reason for every
# skip. Each part that finds a problem, or can't run, fails the one check.
realm_infra() {
  local infra="$root/infra"
  [ -n "$(find "$infra" -name '*.tf' -not -path '*/.terraform/*' -print -quit 2>/dev/null)" ] \
    || return 0
  step "realm: infrastructure (Terraform: format, validate, lock files, tflint, checkov $CHECKOV_VERSION)"
  ran=$((ran + 1))
  local tools tf tflint ruleset ok=1
  if ! tools="$(bash "$root/scripts/realm/tools.sh" terraform tflint tflint-ruleset-aws)"; then
    bad "Terraform, tflint or its AWS ruleset couldn't be fetched (above), so infra/ can't be checked."
    fail=1
    return 0
  fi
  { read -r tf; read -r tflint; read -r ruleset; } <<<"$tools"
  local quiet=(env TF_IN_AUTOMATION=1 CHECKPOINT_DISABLE=1)

  # Format, in place: fmt -check only reads.
  if "${quiet[@]}" "$tf" -chdir="$infra" fmt -check -recursive -diff -no-color; then
    say "   format: clean"
  else
    bad "   format: the files above aren't formatted (terraform fmt -recursive infra)"; ok=0
  fi

  # Validity, in a copy: init writes .terraform/ and lock files. The provider plugins are cached
  # between runs; a root with a committed lock file is held to it (-lockfile=readonly).
  local copy dir rel said lock
  copy="$(mktemp -d)"
  tar -C "$root" --exclude=.terraform -cf - infra | tar -C "$copy" -xf -
  local cache="${TF_PLUGIN_CACHE_DIR:-$root/.realm/terraform/plugins}"
  mkdir -p "$cache"
  while IFS= read -r dir; do
    rel="infra${dir#"$copy/infra"}"
    lock=()
    [ -f "$dir/.terraform.lock.hcl" ] && lock=(-lockfile=readonly)
    if said="$("${quiet[@]}" TF_PLUGIN_CACHE_DIR="$cache" TF_PLUGIN_CACHE_MAY_BREAK_DEPENDENCY_LOCK_FILE=true \
                 "$tf" -chdir="$dir" init -backend=false -input=false -no-color "${lock[@]}" 2>&1)" \
       && said="$("${quiet[@]}" "$tf" -chdir="$dir" validate -no-color 2>&1)"; then
      say "   valid: $rel"
    else
      printf '%s\n' "$said" | sed 's/^/     /'
      bad "   invalid: $rel (above)"; ok=0
    fi
  done < <(find "$copy/infra" -name '*.tf' -not -path '*/.terraform/*' -exec dirname {} \; | sort -u)
  rm -rf "$copy"

  # A committed lock file in every root: the bootstrap, and each environment.
  for dir in "$infra/bootstrap" "$infra"/envs/*; do
    [ -n "$(find "$dir" -maxdepth 1 -name '*.tf' -print -quit 2>/dev/null)" ] || continue
    rel="${dir#"$root"/}"
    if git -C "$root" ls-files --error-unmatch "$rel/.terraform.lock.hcl" >/dev/null 2>&1; then
      say "   lock file: $rel"
    else
      bad "   $rel has no committed .terraform.lock.hcl. There: terraform providers lock"
      bad "     -platform=linux_amd64 -platform=linux_arm64 -platform=darwin_amd64 -platform=darwin_arm64"
      ok=0
    fi
  done

  # tflint, with the AWS ruleset from tools.sh put where tflint looks for it. The config's path
  # is absolute: with a relative one, --recursive leaves the ruleset out of every subdirectory.
  local version="${ruleset##*-}" plugins="${TFLINT_PLUGIN_DIR:-$root/.realm/tflint/plugins}"
  if ! grep -Eq "version *= *\"$version\"" "$infra/.tflint.hcl" 2>/dev/null; then
    bad "   tflint: infra/.tflint.hcl must enable the AWS ruleset at version $version (tools.sh's pin)"; ok=0
  else
    mkdir -p "$plugins/github.com/terraform-linters/tflint-ruleset-aws/$version"
    cp "$ruleset" "$plugins/github.com/terraform-linters/tflint-ruleset-aws/$version/tflint-ruleset-aws"
    if (cd "$infra" && TFLINT_PLUGIN_DIR="$plugins" "$tflint" --recursive --config="$infra/.tflint.hcl" \
          --minimum-failure-severity=error --no-color); then
      say "   tflint: no errors"
    else
      bad "   tflint: the errors above (warnings don't fail)"; ok=0
    fi
  fi

  # checkov, and a reason beside every skip (checkov itself takes a skip without one).
  if ! command -v uvx >/dev/null 2>&1; then
    bad "   checkov: uvx (from uv) isn't on PATH. Install uv: https://docs.astral.sh/uv/"; ok=0
  elif uvx --quiet --from "checkov==$CHECKOV_VERSION" checkov -d "$infra" --framework terraform \
         --quiet --compact; then
    say "   checkov: no failed checks"
  else
    bad "   checkov: the failed checks above, or it couldn't run"; ok=0
  fi
  "$root/scripts/realm/realm" checkov-skips || ok=0

  [ "$ok" -eq 1 ] || fail=1
}

realm_checks
