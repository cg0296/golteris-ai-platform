#!/bin/bash
# scripts/restore.sh — Postgres restore from backup (#53).
#
# Restores a golteris database from a pg_dump backup file.
#
# Usage:
#   ./scripts/restore.sh backups/golteris_20260407_170000.sql.gz
#
# WARNING: This DROPS and recreates the target database. All current
# data will be lost. Use with extreme caution in production.
#
# RTO target: < 4 hours (most restores complete in minutes for our data size)
#
# Restore drill checklist:
#   1. Verify backup file exists and is recent
#   2. Stop the worker process (prevent new writes during restore)
#   3. Run this script
#   4. Verify data: check RFQ counts, latest timestamps, user accounts
#   5. Restart the worker
#   6. Verify the app loads and polls correctly
#   7. Document the drill result in the runbook

set -euo pipefail

BACKUP_FILE="${1:?Usage: ./scripts/restore.sh <backup_file>}"

# Configuration
DB_HOST="${PGHOST:-localhost}"
DB_PORT="${PGPORT:-5432}"
DB_NAME="${PGDATABASE:-golteris}"
DB_USER="${PGUSER:-golteris}"

if [ ! -f "${BACKUP_FILE}" ]; then
  echo "ERROR: Backup file not found: ${BACKUP_FILE}"
  exit 1
fi

echo "[$(date -Iseconds)] Starting restore of ${DB_NAME} from ${BACKUP_FILE}"
echo "WARNING: This will DROP and recreate the database. All current data will be lost."
read -p "Continue? (yes/no): " CONFIRM
if [ "${CONFIRM}" != "yes" ]; then
  echo "Restore cancelled."
  exit 0
fi

# Restore from the backup file
pg_restore \
  -h "${DB_HOST}" \
  -p "${DB_PORT}" \
  -U "${DB_USER}" \
  -d "${DB_NAME}" \
  --clean \
  --if-exists \
  --no-owner \
  --no-privileges \
  "${BACKUP_FILE}"

echo "[$(date -Iseconds)] Restore complete. Verify data integrity:"
echo "  psql -h ${DB_HOST} -U ${DB_USER} -d ${DB_NAME} -c 'SELECT COUNT(*) FROM rfqs;'"
echo "  psql -h ${DB_HOST} -U ${DB_USER} -d ${DB_NAME} -c 'SELECT MAX(created_at) FROM messages;'"
echo "  psql -h ${DB_HOST} -U ${DB_USER} -d ${DB_NAME} -c 'SELECT COUNT(*) FROM users;'"
