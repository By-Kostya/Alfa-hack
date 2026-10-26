#!/bin/sh
# Recreate a crashed cabinet service. Never deletes volumes.
set -eu

root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
cd "$root"
stamp_dir=${TMPDIR:-/tmp}/alfa-credit-heal
mkdir -p "$stamp_dir"
now=$(date +%s)
cooldown=45

cooled() {
  service=$1
  file=$stamp_dir/$service
  if [ -f "$file" ]; then
    last=$(cat "$file")
    if [ $((now - last)) -lt $cooldown ]; then
      return 1
    fi
  fi
  printf '%s' "$now" > "$file"
  return 0
}

healthy() {
  docker compose exec -T backend python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')" >/dev/null 2>&1
}

if healthy; then
  exit 0
fi

if cooled backend; then
  docker compose up -d --force-recreate --no-deps backend
  sleep 8
fi

if healthy; then
  exit 0
fi

if cooled credit-db; then
  docker compose up -d --force-recreate --no-deps credit-db
  docker compose up -d --force-recreate --no-deps backend
fi
