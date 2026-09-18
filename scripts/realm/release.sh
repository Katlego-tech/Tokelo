#!/usr/bin/env bash
# release.sh -- build, stage, promote and roll back a release (DESIGN.md §5.2).
#
#   bash scripts/realm/release.sh build    <version>   images, SBOMs, a signed provenance
#   bash scripts/realm/release.sh publish  <version>   archive the images in [deploy] registry
#   bash scripts/realm/release.sh stage    <version>   staging, the release checks, the record
#   bash scripts/realm/release.sh promote  <version> [--emergency "<reason>"]
#                                                      production, then the watch window
#   bash scripts/realm/release.sh rollback <version>   put an earlier release back in production
#
# v0.0.0 is the seed on the aws platform: built and published, so the infrastructure can create
# each service from it, but never staged or promoted (DESIGN.md §14.3).
# Everything goes to dist/<version>/ (ignored by git; the release workflow keeps it):
#   <service>.tar          the image, exactly as built (docker archive with an OCI index)
#   <service>.cdx.json     its SBOM (CycloneDX, by syft)
#   <service>.vulns.json   known vulnerabilities in it (osv-scanner): recorded, not blocking
#   release.json           the provenance: version, commit, digests, reproducibility, SBOM hashes
#   release.bundle         release.json's signature (cosign, the project key; no public log)
#
# Each image is built twice from scratch, for linux/amd64, with the commit's time as
# SOURCE_DATE_EPOCH and file times rewritten to it. Identical digests mean the build is
# reproducible. In the assured tier a difference stops the release; in the standard tier it's
# recorded in release.json. Only a commit on main is built: a tag can point anywhere.
#
# Signing needs the project's private key: COSIGN_PRIVATE_KEY (its contents) or COSIGN_KEY (a
# path), with COSIGN_PASSWORD. The public half, cosign.pub, is committed at the repo root.
#
# The performance scripts (perf/*.js) get BASE_URL_<SERVICE> for each web service, and each
# KEY=value line of PERF_ENV (a secret, such as a test user's password) as __ENV.KEY.

set -euo pipefail
root="$(git rev-parse --show-toplevel)"
cd "$root"
realm="$root/scripts/realm/realm"

# The builds run in a BuildKit of this exact version (its own container, via buildx), so every
# machine builds the same way, and any Docker can export the images to a file.
BUILDKIT_IMAGE="moby/buildkit:v0.33.0@sha256:6c2fa84a6b61ccd72899dde4239f8d5717f05f9a8ca6f3cad185fb1a95a94de3"
BUILDER="realm-buildkit-v0.33.0"
# The release checks' tools, as containers pinned by digest, and pa11y (with axe) through npx.
K6_IMAGE="grafana/k6:2.2.0@sha256:9bd01d6941fca969cb61bb57d2da5ee9b385fe2aa8881df3798c196564d6ace6"
ZAP_IMAGE="ghcr.io/zaproxy/zaproxy:2.17.0@sha256:781a2bdaea47324e7bab583e2263f21d257b0aee61ed51521a5be45f5f5081ef"
PA11Y="pa11y@10.0.0"
# skopeo's plain version tags are rebuilt daily and their old digests soon vanish from quay.io;
# the -immutable tag is the one upstream keeps for pinning.
SKOPEO_IMAGE="quay.io/skopeo/stable:v1.22.2-immutable@sha256:4a16d57b37617a04b3d643079a477a2848efe892dffcdf0ce56df4262b65f810"

say() { printf '%s\n' "$*"; }
step() { printf '\n-> %s\n' "$*"; }
die() { printf '!! %s\n' "$*" >&2; exit 1; }

ensure_builder() {
  docker buildx inspect "$BUILDER" >/dev/null 2>&1 && return 0
  docker buildx create --name "$BUILDER" --driver docker-container \
    --driver-opt "image=$BUILDKIT_IMAGE" >/dev/null \
    || die "couldn't create the $BUILDER buildx builder"
}

on_main() {  # on_main <commit>: refuse a commit that isn't on main (origin's, when there is one)
  local main=refs/heads/main
  git show-ref --verify --quiet refs/remotes/origin/main && main=refs/remotes/origin/main
  git show-ref --verify --quiet "$main" || die "no main branch: a release is built from a commit on main"
  git merge-base --is-ancestor HEAD "$main" \
    || die "HEAD (${1:0:7}) isn't on ${main#refs/*/}: a release is built only from a commit merged into main"
}

digest_of() {  # the image manifest digest inside a built archive
  tar -xOf "$1" index.json | python3 -c 'import json,sys; print(json.load(sys.stdin)["manifests"][0]["digest"])'
}

build() {
  local version="$1" out="dist/$1" tier name commit epoch syft osv cosign key
  tier="$("$realm" release config realm.tier)"
  name="$("$realm" release config realm.name)"
  commit="$(git rev-parse HEAD)"
  epoch="$(git log -1 --format=%ct HEAD)"
  on_main "$commit"
  [ -f cosign.pub ] || die "no cosign.pub at the repo root: commit the project's public signing key"
  if [ -n "${COSIGN_PRIVATE_KEY:-}" ]; then key="env://COSIGN_PRIVATE_KEY"
  elif [ -n "${COSIGN_KEY:-}" ]; then key="$COSIGN_KEY"
  else die "set COSIGN_PRIVATE_KEY (or COSIGN_KEY, a path) and COSIGN_PASSWORD: releases are signed"
  fi
  { read -r syft; read -r osv; read -r cosign; } < <(bash scripts/realm/tools.sh syft osv-scanner cosign)
  command -v docker >/dev/null || die "docker isn't on PATH: images are built with docker buildx"
  ensure_builder

  local services
  services="$("$realm" release services)" || die "realm.toml's [[service]] entries need fixing"
  rm -rf "$out"; mkdir -p "$out"
  say "== build $version at ${commit:0:7} (tier: $tier) =="
  while IFS=$'\t' read -r svc context dockerfile _port _health _ui _k; do
    local image="realm-$name-$svc:$version" first second reproducible
    step "$svc: two builds from scratch"
    for i in 1 2; do
      SOURCE_DATE_EPOCH="$epoch" docker buildx build --builder "$BUILDER" --quiet --no-cache \
        --platform linux/amd64 --build-arg SOURCE_DATE_EPOCH -f "$context/$dockerfile" \
        --output "type=docker,dest=$out/$svc.$i.tar,name=$image,rewrite-timestamp=true" \
        "$context" >/dev/null || die "$svc: docker build failed"
    done
    first="$(digest_of "$out/$svc.1.tar")"; second="$(digest_of "$out/$svc.2.tar")"
    if [ "$first" = "$second" ]; then
      reproducible=yes; say "   reproducible: both builds are $first"
    else
      reproducible=no; say "   NOT reproducible: $first, then $second"
      [ "$tier" = assured ] && die "$svc: the assured tier needs a reproducible build (pin the base image by digest, pin OS packages, embed no build times)"
    fi
    mv "$out/$svc.1.tar" "$out/$svc.tar"; rm -f "$out/$svc.2.tar"
    docker load -q -i "$out/$svc.tar" >/dev/null

    step "$svc: SBOM (syft) and known vulnerabilities (osv-scanner)"
    SYFT_FILE_METADATA_SELECTION=none "$syft" scan -q "docker-archive:$out/$svc.tar" \
      -o "cyclonedx-json=$out/$svc.cdx.json" || die "$svc: syft couldn't read the image"
    local rc=0
    "$osv" scan image --archive "$out/$svc.tar" --format json \
      --output-file "$out/$svc.vulns.json" >/dev/null 2>&1 || rc=$?
    case "$rc" in 0|1) ;; *) die "$svc: osv-scanner couldn't scan the image (exit $rc)" ;; esac
    printf '%s\t%s\t%s\t%s\t%s\n' "$svc" "$image" "$first" "$reproducible" "$svc.cdx.json" \
      >> "$out/build.tsv"
  done <<<"$services"

  step "provenance and signature"
  "$realm" release provenance "$version" >/dev/null || die "couldn't write release.json"
  "$cosign" sign-blob --yes --key "$key" --use-signing-config=false --tlog-upload=false \
    --bundle "$out/release.bundle" "$out/release.json" >/dev/null 2>&1 \
    || die "cosign couldn't sign release.json (is COSIGN_PASSWORD right for the key?)"
  "$cosign" verify-blob --key cosign.pub --bundle "$out/release.bundle" \
    --insecure-ignore-tlog=true "$out/release.json" >/dev/null 2>&1 \
    || die "release.json's signature doesn't verify against cosign.pub: the key pair doesn't match"
  say "   release.json signed; it verifies against cosign.pub"
  say ""
  say "== built $version: $(wc -l < "$out/build.tsv") image(s) in $out =="
}

# ------------------------------------------------------------ the release checks ---
adapter() { "$root/scripts/realm/deploy/$platform.sh" "$@"; }

one_line() {  # one_line <text>: its last line, fit for a record's table cell
  printf '%s\n' "$1" | grep -v '^[[:space:]]*$' | tail -1 | tr '\t|' '  ' | cut -c1-400
}

check() {  # check <name> <target> <pass|fail|not applicable> <detail>
  printf '%s\t%s\t%s\t%s\n' "$1" "$2" "$3" "$4" >> "$checks"
  printf '   %-22s %-16s %s  %s\n' "$1" "$2" "$3" "$4"
}

healthy() {  # healthy <url> <path>: the service answers 200 there within a minute
  local _
  for _ in $(seq 1 30); do
    curl -fsS --max-time 5 "$1$2" >/dev/null 2>&1 && return 0
    sleep 2
  done
  return 1
}

deploy_all() {  # deploy_all <env> <version>: every service; each result as a check row
  local env="$1" version="$2" svc ref said ok=0
  while IFS=$'\t' read -r svc _c _d _p _h _u _k; do
    if ! ref="$("$realm" release ref "$version" "$svc")"; then
      said="$ref"
    elif said="$(adapter deploy "$env" "$svc" "$ref" 2>&1)"; then
      check "deploy $env" "$svc" pass "$version"; continue
    fi
    check "deploy $env" "$svc" fail "$version didn't deploy: $(one_line "$said")"; ok=1
  done <<<"$services"
  return "$ok"
}

smoke_all() {  # smoke_all <env> [label]: every web service's health path answers; every worker
  local env="$1" label="${2:-smoke}" svc health kind url said ok=0  # passes the adapter's health
  while IFS=$'\t' read -r svc _c _d _p health _u kind; do
    if [ "$kind" = worker ]; then
      if said="$(adapter health "$env" "$svc" 2>&1)"; then
        check "$label" "$svc" pass "health: $(one_line "$said")"
      else
        check "$label" "$svc" fail "health: $(one_line "$said")"; ok=1
      fi
      continue
    fi
    url="$(adapter url "$env" "$svc")"
    if healthy "$url" "$health"; then check "$label" "$svc" pass "$health answered 200"
    else check "$label" "$svc" fail "$health didn't answer 200"; ok=1
    fi
  done <<<"$services"
  return "$ok"
}

base_urls() {  # -e BASE_URL_<SERVICE>=<url> for every web service in <env>, for k6
  local svc kind
  while IFS=$'\t' read -r svc _c _d _p _h _u kind; do
    [ "$kind" = web ] || continue
    printf -- '-e\nBASE_URL_%s=%s\n' "$(printf '%s' "$svc" | tr 'a-z-' 'A-Z_')" "$(adapter url "$1" "$svc")"
  done <<<"$services"
}

perf=()  # PERF_ENV's KEY=value pairs, once perf_env has checked them
perf_env() {  # the secret PERF_ENV's KEY=value lines, checked, into the array perf (not exported)
  local pairs pair
  pairs="$("$realm" release perf-env)" || { printf '%s\n' "$pairs" >&2; die "fix the PERF_ENV secret"; }
  perf=()
  while IFS= read -r pair; do [ -z "$pair" ] || perf+=("$pair"); done <<<"$pairs"
}

k6_run() {  # k6_run <script> <log> [docker args]: k6 in its container; PERF_ENV's values reach it
  local script="$1" log="$2" pair names=()  # through the environment, never on a command line
  shift 2
  for pair in "${perf[@]}"; do names+=(-e "${pair%%=*}"); done
  (
    for pair in "${perf[@]}"; do export "${pair?}"; done
    docker run --rm --network host "$@" "${names[@]}" -v "$root/perf:/perf:ro" "$K6_IMAGE" \
      run --quiet "/perf/$script"
  ) > "$log" 2>&1
}

setup_release() {  # the settings every command after build needs
  version="$1"; out="$root/dist/$version"; checks="$out/checks.tsv"
  mkdir -p "$out"
  platform="$("$realm" release config deploy.platform)"
  "$realm" release deploy-check || die "fix realm.toml's [deploy] settings first"
  services="$("$realm" release services)" || die "realm.toml's [[service]] entries need fixing"
}

archived() {  # archived <image>: the digest the registry holds under that tag (fails if none);
  # publish's registry settings ($tls, $user, $token) apply
  docker run --rm --network host "$SKOPEO_IMAGE" inspect --tls-verify="$tls" \
    --creds "$user:$token" --format '{{.Digest}}' "docker://$1" 2>/dev/null
}

publish() {  # push each image archive to the registry, keeping its digest (skopeo)
  setup_release "$1"
  [ -f "$out/release.json" ] || die "no dist/$version/release.json: build $version first"
  local registry svc image digest pushed
  registry="$("$realm" release config deploy.registry)"
  [ -n "$registry" ] || die "[deploy] registry is empty: nowhere to archive the images"
  local user="${REGISTRY_USER:-}" token="${REGISTRY_TOKEN:-}"
  if [[ "$registry" =~ ^[0-9]{12}\.dkr\.ecr\.([a-z0-9-]+)\.amazonaws\.com/ ]] && [ "$user" != AWS ]; then
    # ECR takes only its own short-lived token, as user AWS. In CI, REGISTRY_USER is the GitHub
    # actor (for GHCR), so it's ignored here; set REGISTRY_USER=AWS to supply a token yourself.
    user=AWS
    token="$(aws ecr get-login-password --region "${BASH_REMATCH[1]}")" \
      || die "couldn't get an ECR token from the AWS CLI (signed in? in CI, the release role)"
  fi
  [ -n "$user" ] && [ -n "$token" ] \
    || die "set REGISTRY_USER and REGISTRY_TOKEN (in CI: the actor and GITHUB_TOKEN)"
  local tls=true
  [ "${REALM_REGISTRY_INSECURE:-}" = 1 ] && tls=false   # a plain-HTTP registry, e.g. on localhost
  while IFS=$'\t' read -r svc _c _d _p _h _u _k; do
    image="$registry/$svc:$version"
    digest="$(digest_of "$out/$svc.tar")"
    step "$svc -> $image"
    # A re-run finds the image already there: pushed again, an immutable tag (ECR's) would refuse.
    if [ "$(archived "$image")" = "$digest" ]; then
      say "   already archived with its digest: $digest"
      continue
    fi
    docker run --rm --network host -v "$out:/release:ro" "$SKOPEO_IMAGE" copy --quiet \
      --preserve-digests --dest-tls-verify="$tls" --dest-creds "$user:$token" \
      "oci-archive:/release/$svc.tar" "docker://$image" || die "$svc: skopeo couldn't push to $image"
    pushed="$(archived "$image")" || die "$svc: couldn't read $image back"
    [ "$pushed" = "$digest" ] || die "$svc: the registry holds $pushed, not the built $digest"
    say "   archived with its digest: $digest"
  done <<<"$services"
}

stage() {
  [ "$1" != v0.0.0 ] || die "v0.0.0 is the seed; it's archived, never staged"
  setup_release "$1"
  [ -f "$out/release.json" ] || die "no dist/$version/release.json: build $version first"
  "$realm" gate-passed Development || die "the Development gate hasn't passed yet (GATES.md)"
  "$realm" release slo-check || die "every web service needs its objectives in docs/ops/slo.toml"
  perf_env
  : > "$checks"
  say "== stage $version on $platform =="

  step "deploy to staging"
  deploy_all staging "$version" || true
  step "smoke"
  smoke_all staging || true

  step "performance (k6, against the NFR targets in perf/)"
  local scripts=() script
  [ -d perf ] && while IFS= read -r script; do scripts+=("$script"); done < <(find perf -maxdepth 1 -name '*.js' | sort)
  if [ "${#scripts[@]}" -eq 0 ]; then
    check performance "perf/" "not applicable" "no perf/*.js scripts"
  else
    local envs=()
    mapfile -t envs < <(base_urls staging)
    for script in "${scripts[@]}"; do
      if k6_run "$(basename "$script")" "$out/k6-$(basename "$script" .js).log" "${envs[@]}"; then
        check performance "$script" pass "every threshold held"
      else
        check performance "$script" fail "a threshold broke: dist/$version/k6-$(basename "$script" .js).log"
      fi
    done
  fi

  step "accessibility (pa11y with axe, on web services with ui = true)"
  local svc ui kind any_ui=0 url
  printf '{"runners": ["axe"], "chromeLaunchConfig": {"args": ["--no-sandbox"]}}\n' > "$out/pa11y.json"
  while IFS=$'\t' read -r svc _c _d _p _h ui kind; do
    [ "$ui" = true ] && [ "$kind" = web ] || continue
    any_ui=1; url="$(adapter url staging "$svc")"
    if ! command -v npx >/dev/null 2>&1; then
      check accessibility "$svc" fail "npx (Node) isn't on PATH, so pa11y can't run"
    elif npx --yes "$PA11Y" --config "$out/pa11y.json" --reporter cli "$url/" > "$out/pa11y-$svc.log" 2>&1; then
      check accessibility "$svc" pass "no axe issues on /"
    else
      check accessibility "$svc" fail "axe found issues: dist/$version/pa11y-$svc.log"
    fi
  done <<<"$services"
  [ "$any_ui" -eq 1 ] || check accessibility "-" "not applicable" "no service has ui = true"

  step "DAST (the OWASP ZAP baseline scan, on web services)"
  mkdir -p "$out/zap"; chmod 777 "$out/zap"
  "$realm" release zap-rules "$out/zap/rules.tsv" >/dev/null || die "fix docs/release/zap-rules.tsv"
  local rules=() rc
  [ -s "$out/zap/rules.tsv" ] && rules=(-c rules.tsv)
  while IFS=$'\t' read -r svc _c _d _p _h _u kind; do
    [ "$kind" = web ] || continue
    url="$(adapter url staging "$svc")"
    local attempt
    for attempt in 1 2; do  # exit 3 is ZAP failing to run, not a finding: one more try
      rc=0
      docker run --rm --network host -v "$out/zap:/zap/wrk:rw" "$ZAP_IMAGE" \
        zap-baseline.py -t "$url/" "${rules[@]}" -J "zap-$svc.json" > "$out/zap-$svc.log" 2>&1 || rc=$?
      [ "$rc" -eq 3 ] || break
      [ "$attempt" -eq 1 ] && say "   ZAP didn't run cleanly (exit 3); trying once more"
    done
    case "$rc" in
      0) check DAST "$svc" pass "no warnings or failures" ;;
      3) check DAST "$svc" fail "ZAP couldn't run, twice: dist/$version/zap-$svc.log" ;;
      *) check DAST "$svc" fail "$(grep -E '^FAIL-NEW' "$out/zap-$svc.log" | tr -s '\t' ' ' || echo "zap exited $rc"): dist/$version/zap-$svc.log" ;;
    esac
  done <<<"$services"

  step "rollback drill"
  local previous
  previous="$("$realm" release previous "$version")"
  if [ -z "$previous" ]; then
    check "rollback drill" "-" "not applicable" "the first release: nothing to roll back to"
  elif deploy_all staging "$previous" && smoke_all staging "drill: $previous" \
       && deploy_all staging "$version" && smoke_all staging "drill: back to $version"; then
    check "rollback drill" "-" pass "$version -> $previous -> $version on staging"
  else
    check "rollback drill" "-" fail "see the rows above"
  fi

  step "release record"
  "$realm" release record-staged "$version" "$checks"
}

promote() {
  setup_release "$1"; shift
  local emergency=""
  [ "${1:-}" = --emergency ] && emergency="${2:-}"
  [ "${1:-}" = --emergency ] && [ -z "$emergency" ] && die "--emergency needs the reason"
  "$realm" release promotable "$version" ${emergency:+--emergency "$emergency"} \
    || die "$version can't be promoted yet (see above)"
  : > "$checks"
  local previous
  previous="$("$realm" release previous "$version")"
  say "== promote $version to production${previous:+ (replacing $previous)} =="

  step "deploy to production"
  local failed=0
  deploy_all production "$version" && smoke_all production || failed=1

  if [ "$failed" -eq 0 ]; then
    step "watch window (k6 against docs/ops/slo.toml)"
    local urls=() svc kind
    while IFS=$'\t' read -r svc _c _d _p _h _u kind; do
      [ "$kind" = web ] || continue
      urls+=("$svc=$(adapter url production "$svc")")
    done <<<"$services"
    if [ "${#urls[@]}" -eq 0 ]; then
      "$realm" release record-promoted "$version" ${emergency:+--emergency "$emergency"} \
        --watch "none: no web service to watch (the workers passed their health checks)"
      say ""; say "== $version is live =="
      return 0
    fi
    "$realm" release watch-script "${urls[@]}" > "$out/watch.js" || die "couldn't write the watch script"
    if docker run --rm --network host -v "$out:/watch:ro" "$K6_IMAGE" run --quiet /watch/watch.js \
         > "$out/watch.log" 2>&1; then
      local minutes rate
      minutes="$(sed -n "s/.*duration: '\([0-9]*\)s'.*/\1/p" "$out/watch.js")"
      rate="$(sed -n 's/.*rate: \([0-9]*\),.*/\1/p' "$out/watch.js")"
      "$realm" release record-promoted "$version" ${emergency:+--emergency "$emergency"} \
        --watch "${minutes}s at ${rate} requests a second: every objective held"
      say ""; say "== $version is live =="
      return 0
    fi
    failed=2
  fi

  step "roll back"
  local reason detail="$out/incident.txt"
  if [ "$failed" -eq 2 ]; then
    reason="an objective broke in the watch window"
    { echo "The watch window's k6 thresholds (from docs/ops/slo.toml) broke:"; echo
      grep -E '✗|crossed|thresholds' "$out/watch.log" | head -20 | sed 's/^/    /'; } > "$detail"
  else
    reason="the production deploy or its smoke test failed"
    grep -P '\tfail\t' "$checks" | sed 's/^/    /' > "$detail" || true
  fi
  if [ -n "$previous" ]; then
    deploy_all production "$previous" && smoke_all production "restored: $previous" \
      || say "!! the rollback to $previous didn't come up healthy: act now"
  fi
  local inc
  inc="$("$realm" release incident "$version" --to "$previous" --detail-file "$detail")"
  "$realm" release record-rolled-back "$version" --to "$previous" --reason "$reason ($inc)"
  die "$version was rolled back: $reason. $inc is open in docs/ops/incidents/"
}

rollback() {
  [ "$1" != v0.0.0 ] || die "v0.0.0 is the seed: it was never staged, so it never goes to production"
  setup_release "$1"
  : > "$checks"
  say "== roll production back to $version =="
  deploy_all production "$version" && smoke_all production || die "the rollback to $version didn't come up healthy"
  "$realm" release record-rollback "$version"
}

[ $# -ge 2 ] || { sed -n '2,29p' "$0"; exit 2; }
command="$1" version_arg="$2"
[[ "$version_arg" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "a version looks like v1.4.0"
case "$command" in
  build)    build "$version_arg" ;;
  publish)  publish "$version_arg" ;;
  stage)    stage "$version_arg" ;;
  promote)  shift 2; promote "$version_arg" "$@" ;;
  rollback) rollback "$version_arg" ;;
  *) die "unknown command '$command' (build, publish, stage, promote, rollback)" ;;
esac
