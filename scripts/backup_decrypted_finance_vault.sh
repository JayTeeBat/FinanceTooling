#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  scripts/backup_decrypted_finance_vault.sh [--dry-run] [--no-check] [--no-forget]

Back up the mounted, decrypted FinanceVault data directory into an encrypted
restic repository.

Required:
  RESTIC_REPOSITORY       Restic repository path or URL.

Optional:
  RESTIC_PASSWORD         Restic password, if not using restic's interactive prompt.
  RESTIC_PASSWORD_FILE    Restic password file.
  FINANCE_DATA_PATH       Decrypted data root to back up.
  FINANCE_PROCESSED_PATH  Used for workflow-status and summary capture.
  FINANCE_STATEMENTS_PATH Used for workflow-status.

Defaults:
  FINANCE_DATA_PATH is inferred from FINANCE_STATEMENTS_PATH/.. when available.
  Otherwise it falls back to the current .env FinanceVault data path.

EOF
}

DRY_RUN=false
RUN_CHECK=true
RUN_FORGET=true

while (($#)); do
  case "$1" in
    --dry-run)
      DRY_RUN=true
      ;;
    --no-check)
      RUN_CHECK=false
      ;;
    --no-forget)
      RUN_FORGET=false
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

load_env_file() {
  local env_file="$1"
  if [[ ! -f "$env_file" ]]; then
    return
  fi
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "$line" || "$line" == \#* ]] && continue
    [[ "$line" == *=* ]] || continue
    local key="${line%%=*}"
    local value="${line#*=}"
    case "$key" in
      FINANCE_*|RESTIC_*)
        if [[ -z "${!key:-}" ]]; then
          export "$key=$value"
        fi
        ;;
    esac
  done < "$env_file"
}

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/.." && pwd)"

load_env_file "$repo_root/.env"

require_command restic
require_command date

if [[ -z "${RESTIC_REPOSITORY:-}" ]]; then
  echo "RESTIC_REPOSITORY is required." >&2
  echo "Example: export RESTIC_REPOSITORY=/mnt/backup-drive/finance-restic" >&2
  exit 1
fi

if [[ -z "${FINANCE_DATA_PATH:-}" ]]; then
  if [[ -n "${FINANCE_STATEMENTS_PATH:-}" ]]; then
    FINANCE_DATA_PATH="$(cd -- "$FINANCE_STATEMENTS_PATH/.." && pwd)"
  else
    FINANCE_DATA_PATH="/home/thomazo/.local/share/Cryptomator/mnt/FinanceVault/data"
  fi
fi

if [[ ! -d "$FINANCE_DATA_PATH" ]]; then
  echo "Decrypted finance data path does not exist: $FINANCE_DATA_PATH" >&2
  echo "Mount the Cryptomator vault first, or set FINANCE_DATA_PATH." >&2
  exit 1
fi

if [[ ! -r "$FINANCE_DATA_PATH" ]]; then
  echo "Decrypted finance data path is not readable: $FINANCE_DATA_PATH" >&2
  exit 1
fi

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
manifest_dir="$repo_root/.tmp/finance_backup_manifests"
manifest_path="$manifest_dir/finance-backup-$timestamp.txt"
mkdir -p "$manifest_dir"

{
  echo "finance_backup_started_at=$timestamp"
  echo "finance_data_path=$FINANCE_DATA_PATH"
  echo "restic_repository=$RESTIC_REPOSITORY"
  echo
  echo "## workflow-status"
} > "$manifest_path"

if command -v uv >/dev/null 2>&1; then
  if (
    cd "$repo_root"
    uv run workflow-status
  ) >> "$manifest_path" 2>&1; then
    echo "workflow_status=pass" >> "$manifest_path"
  else
    echo "workflow_status=failed" >> "$manifest_path"
    echo "workflow-status failed; see $manifest_path" >&2
    exit 1
  fi
else
  echo "workflow_status=skipped_uv_missing" >> "$manifest_path"
fi

summary_path="${FINANCE_PROCESSED_PATH:-$FINANCE_DATA_PATH/processed}/outputs/transform_run_summary.json"
if [[ -f "$summary_path" ]]; then
  {
    echo
    echo "## transform_run_summary.json"
    sed -n '1,220p' "$summary_path"
  } >> "$manifest_path"
else
  {
    echo
    echo "summary_status=missing"
    echo "summary_path=$summary_path"
  } >> "$manifest_path"
fi

echo "Manifest: $manifest_path"
echo "Repository: $RESTIC_REPOSITORY"
echo "Source: $FINANCE_DATA_PATH"

backup_args=(
  backup "$FINANCE_DATA_PATH"
  --tag finance-vault-decrypted
  --tag finance-tooling
  --tag "$timestamp"
)

if [[ "$DRY_RUN" == true ]]; then
  backup_args+=(--dry-run)
fi

restic "${backup_args[@]}"

if [[ "$DRY_RUN" == true ]]; then
  echo "Dry run complete. No snapshot was written."
  exit 0
fi

restic backup "$manifest_path" \
  --tag finance-vault-decrypted \
  --tag finance-tooling \
  --tag backup-manifest \
  --tag "$timestamp"

if [[ "$RUN_FORGET" == true ]]; then
  restic forget \
    --tag finance-vault-decrypted \
    --keep-daily 14 \
    --keep-weekly 8 \
    --keep-monthly 12 \
    --prune
fi

if [[ "$RUN_CHECK" == true ]]; then
  restic check
fi

echo "Latest finance-vault-decrypted snapshots:"
restic snapshots --tag finance-vault-decrypted --latest 5
