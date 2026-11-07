#!/usr/bin/env bash
# Copy the integration from this checkout to a Home Assistant host over SSH,
# then restart the HA container so the new Python code is loaded.
#
# Usage: scripts/deploy.sh [-n|--dry-run] [--no-restart] [-f|--logs]
#
#   -n, --dry-run   show what would change on the host, change nothing
#   --no-restart    copy files but leave Home Assistant running
#   -f, --logs      after restarting, follow the HA log filtered on "ipixel_color_se"
#
# The target folder is mirrored: files that are not in this repo are deleted
# from it (except __pycache__). Only custom_components/ipixel_color_se is
# touched, never other integrations.
#
# Settings come from the environment or from scripts/deploy.env, which is not
# versioned (copy scripts/deploy.env.example). The environment wins.
#   HA_SSH_HOST    SSH host running Home Assistant   (required)
#   HA_CONFIG_DIR  HA config dir on that host        (required)
#   HA_CONTAINER   Docker container name             (default: homeassistant)
set -euo pipefail

domain="ipixel_color_se"
dry_run=false
restart=true
follow_logs=false

for arg in "$@"; do
  case "$arg" in
    -n|--dry-run) dry_run=true ;;
    --no-restart) restart=false ;;
    -f|--logs) follow_logs=true ;;
    -h|--help) sed -n '2,19p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown option: $arg (see --help)" >&2; exit 1 ;;
  esac
done

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
env_file="$repo_root/scripts/deploy.env"

# Read HA_*=value lines, without running the file and without overriding
# variables already set in the environment
if [[ -f "$env_file" ]]; then
  while IFS='=' read -r key value; do
    [[ "$key" =~ ^HA_[A-Z_]+$ ]] || continue
    value="${value%\"}"
    value="${value#\"}"
    [[ -n "${!key:-}" ]] || export "$key=$value"
  done < "$env_file"
fi

: "${HA_SSH_HOST:?Set HA_SSH_HOST, in the environment or in scripts/deploy.env}"
: "${HA_CONFIG_DIR:?Set HA_CONFIG_DIR, in the environment or in scripts/deploy.env}"
HA_CONTAINER="${HA_CONTAINER:-homeassistant}"

src="$repo_root/custom_components/$domain/"
dest="$HA_CONFIG_DIR/custom_components/$domain/"

if [[ ! -f "$src/manifest.json" ]]; then
  echo "No integration found at $src" >&2
  exit 1
fi

rsync_opts=(-rlt --delete --itemize-changes
  --exclude '__pycache__/' --exclude '.DS_Store')
$dry_run && rsync_opts+=(--dry-run)

echo "→ Syncing to $HA_SSH_HOST:$dest$($dry_run && echo ' (dry run)')"
rsync "${rsync_opts[@]}" "$src" "$HA_SSH_HOST:$dest"

if $dry_run; then
  echo "✓ Dry run complete, nothing was changed"
  exit 0
fi

if ! $restart; then
  echo "✓ Files copied. Restart Home Assistant to load the changes."
  exit 0
fi

# Take the timestamp on the host so --logs only shows lines from this restart
since="$(ssh "$HA_SSH_HOST" date -u +%Y-%m-%dT%H:%M:%SZ)"

echo "→ Restarting container $HA_CONTAINER"
ssh "$HA_SSH_HOST" docker restart "$HA_CONTAINER" >/dev/null
echo "✓ Deployed and restarted"

if $follow_logs; then
  echo "→ Following logs (Ctrl+C to stop)"
  ssh "$HA_SSH_HOST" docker logs -f --since "$since" "$HA_CONTAINER" 2>&1 \
    | grep --line-buffered -i "$domain"
fi
