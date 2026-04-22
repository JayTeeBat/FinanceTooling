# Decrypted Vault Backup

This repo's pipeline creates short-lived workflow snapshots under the finance
data root, but those snapshots are not a disaster-recovery layer. Use
`scripts/backup_decrypted_finance_vault.sh` to back up the mounted, decrypted
FinanceVault data tree into an encrypted restic repository.

## Where This Should Live

Keep the script in this repository under `scripts/` because it is operationally
tied to the FinanceTooling workflow and `.env` conventions. Keep the backup
repository outside the Cryptomator vault, ideally on a local external drive or a
local disk path that is not synced through the same vault.

Do not place the restic repository under:

```text
FinanceVault/data/
FinanceVault/data/backup/
FinanceVault/data/processed/
```

## One-Time Setup

Install `restic`, then choose a local backup repository path. Example:

```bash
export RESTIC_REPOSITORY="/mnt/backup-drive/finance-restic"
restic init
```

Store the restic password somewhere separate from the machine and the backup
drive. If you prefer non-interactive runs, use `RESTIC_PASSWORD_FILE`:

```bash
export RESTIC_PASSWORD_FILE="/path/to/restic-password.txt"
```

## Normal Run

Mount the Cryptomator vault first, then run:

```bash
export RESTIC_REPOSITORY="/mnt/backup-drive/finance-restic"
scripts/backup_decrypted_finance_vault.sh
```

The script:

- loads repo `.env` values when present;
- verifies the decrypted finance data path exists;
- runs `uv run workflow-status` and records the output in a local manifest;
- backs up the decrypted `FinanceVault/data` tree to restic;
- backs up the manifest;
- applies retention;
- runs `restic check`;
- prints recent finance backup snapshots.

Default retention keeps:

```text
14 daily snapshots
8 weekly snapshots
12 monthly snapshots
```

## Useful Options

Preview without writing a backup:

```bash
scripts/backup_decrypted_finance_vault.sh --dry-run
```

Skip retention pruning:

```bash
scripts/backup_decrypted_finance_vault.sh --no-forget
```

Skip `restic check` for a faster run:

```bash
scripts/backup_decrypted_finance_vault.sh --no-check
```

Override the decrypted source path:

```bash
FINANCE_DATA_PATH="/path/to/mounted/FinanceVault/data" \
scripts/backup_decrypted_finance_vault.sh
```

## Restore Drill

Test recovery periodically. Restore the latest snapshot to a temporary location:

```bash
mkdir -p /tmp/finance-restore-test
restic restore latest \
  --tag finance-vault-decrypted \
  --target /tmp/finance-restore-test
```

Then inspect the restored tree and compare it with the latest known-good
workflow baseline. The current expected shape is:

```text
257 raw source files
13576 canonical rows
Pipeline health: pass
Date range: 2016-02-29 -> 2026-03-31
```

For a fuller check, point the workflow env vars at the restored tree and run:

```bash
FINANCE_STATEMENTS_PATH="/tmp/finance-restore-test/<restored-prefix>/data/raw" \
FINANCE_PROCESSED_PATH="/tmp/finance-restore-test/<restored-prefix>/data/processed" \
uv run workflow-status
```

## Recommended Rhythm

- Run before risky cleanup, migration, or bulk review import work.
- Run after meaningful changes to `data/config/`, review state, or canonical
  processed outputs.
- Run at least weekly while actively working in the finance data.
- Do a restore drill monthly, or before relying on backups during cleanup.
