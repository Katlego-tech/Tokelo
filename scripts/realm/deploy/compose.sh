#!/usr/bin/env bash
# deploy/compose.sh -- the compose platform: staging and production on one Docker host.
#
#   compose.sh deploy <env> <service> <image>   run that image for the service; wait until healthy
#   compose.sh live   <env> <service>           print the image the service runs now
#   compose.sh url    <env> <service>           print its base URL
#   compose.sh health <env> <service>           its container runs, and hasn't restarted
#
# Each environment is a Docker Compose project, realm-<name>-<env>, published on 127.0.0.1:
# staging from port 18000 and production from 19000, by each [[service]]'s place in the list.
# Workers (kind = "worker") publish no port: a web service is healthy when its health path
# answers, a worker when its container keeps running. It's how the kit's own tests run a whole
# release, and what one self-hosted box would use. The deploy adapter contract is in DESIGN.md
# §5.2 and §14.3.

set -euo pipefail
root="$(git rev-parse --show-toplevel)"
realm="$root/scripts/realm/realm"

die() { printf '!! compose: %s\n' "$*" >&2; exit 1; }

[ $# -ge 3 ] || die "usage: compose.sh deploy|live|url|health <env> <service> [image]"
action="$1" env="$2" service="$3" image="${4:-}"
case "$env" in
  staging)    base=18000 ;;
  production) base=19000 ;;
  *) die "environment '$env': staging or production" ;;
esac

name="$("$realm" release config realm.name)"
project="realm-$name-$env"
state="$root/.realm/compose/$env"
index=0 port="" health="" kind=""
while IFS=$'\t' read -r svc _context _dockerfile _cport chealth _ui ckind; do
  if [ "$svc" = "$service" ]; then
    port=$((base + index)); health="$chealth"; kind="$ckind"
  fi
  index=$((index + 1))
done < <("$realm" release services)
[ -n "$kind" ] || die "no [[service]] called '$service'"

write_compose() {  # every service deployed so far in this environment, with its image
  {
    echo "# Written by scripts/realm/deploy/compose.sh; the images come from .realm/compose/$env/."
    echo "services:"
    local i=0 svc cport ckind img
    while IFS=$'\t' read -r svc _c _d cport _h _u ckind; do
      if [ -f "$state/$svc.image" ]; then
        img="$(cat "$state/$svc.image")"
        echo "  $svc:"
        echo "    image: $img"
        if [ "$ckind" = web ]; then echo "    ports: [\"127.0.0.1:$((base + i)):$cport\"]"; fi
        echo "    environment:"
        if [ "$cport" != - ]; then echo "      PORT: \"$cport\""; fi
        echo "      REALM_ENV: \"$env\""
        echo "      OTEL_SERVICE_NAME: \"$svc\""
        echo "      OTEL_RESOURCE_ATTRIBUTES: \"service.version=${img##*:},deployment.environment=$env\""
        echo "    restart: unless-stopped"
      fi
      i=$((i + 1))
    done < <("$realm" release services)
  } > "$state/compose.yml"
}

running() {  # the service's container is up and hasn't restarted; otherwise says why, and fails
  local id up restarting restarts code
  id="$(docker compose -p "$project" -f "$state/compose.yml" ps -a -q "$service" 2>/dev/null || true)"
  [ -n "$id" ] || { echo "$service has no container in $env"; return 1; }
  read -r up restarting restarts code < <(docker inspect \
    -f '{{.State.Running}} {{.State.Restarting}} {{.RestartCount}} {{.State.ExitCode}}' "$id") \
    || { echo "couldn't inspect $service's container in $env"; return 1; }
  # The exit code is the last run's only while the container is down: a restarted one reads 0.
  [ "$up" = true ] && code="" || code=" (exit $code)"
  if [ "$restarts" != 0 ]; then echo "$service has restarted $restarts time(s) in $env$code"; return 1; fi
  if [ "$up" != true ] || [ "$restarting" != false ]; then echo "$service isn't running in $env$code"; return 1; fi
  echo "$service is running in $env"
}

case "$action" in
  deploy)
    [ -n "$image" ] || die "deploy needs an image"
    docker image inspect "$image" >/dev/null 2>&1 || die "no image $image on this Docker host"
    mkdir -p "$state"
    printf '%s\n' "$image" > "$state/$service.image"
    write_compose
    docker compose -p "$project" -f "$state/compose.yml" up -d --no-deps "$service" >/dev/null 2>&1 \
      || die "docker compose couldn't start $service in $env"
    if [ "$kind" = worker ]; then  # running at 3 checks in a row, a second apart: a crash at start-up fails
      steady=0
      for _ in $(seq 1 60); do
        if said="$(running)"; then
          steady=$((steady + 1)); [ "$steady" -lt 3 ] || exit 0
        else
          steady=0; case "$said" in *restarted*) die "$said" ;; esac
        fi
        sleep 1
      done
      die "$service in $env didn't keep running for 3 seconds within a minute: $said"
    fi
    for _ in $(seq 1 60); do
      if curl -fsS --max-time 2 "http://127.0.0.1:$port$health" >/dev/null 2>&1; then
        exit 0
      fi
      sleep 1
    done
    die "$service in $env didn't answer $health within 60 seconds"
    ;;
  live)
    id="$(docker compose -p "$project" -f "$state/compose.yml" ps -q "$service" 2>/dev/null || true)"
    [ -n "$id" ] || die "$service isn't running in $env"
    docker inspect --format '{{.Config.Image}}' "$id"
    ;;
  url)
    [ "$kind" = web ] || die "$service is a worker: it has no URL"
    echo "http://127.0.0.1:$port"
    ;;
  health)
    said="$(running)" || die "$said"
    echo "$said"
    ;;
  *) die "unknown action '$action' (deploy, live, url, health)" ;;
esac
