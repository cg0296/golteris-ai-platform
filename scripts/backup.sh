#!/bin/bash
# scripts/backup.sh — Automated Postgres backup script (#53).
#
# Creates a compressed pg_dump of the golteris database and stores it
# in the configured backup directory. Designed to be run by cron daily.
#
# Usage:
#   ./scripts/backup.sh                    # Uses defaults
#   BACKUP_DIR=/mnt/backups ./scripts/backup.sh  # Custom directory
#
# RPO target: < 1 hour (run hourly via cron for production)
# RTO target: < 4 hours (restore from most recent backup)
#
# Cron example (every hour):
#   0 * * * * /path/to/golteris/scripts/backup.sh >> /var/log/golteris-backup.log 2>&1
#
# Render managed Postgres includes automatic daily backups. This script
# provides additional backup control and off-site storage capability.

set -euo pipefail

# Configuration (override via env vars)
DB_HOST="${PGHOST:-localhost}"
DB_PORT="${PGPORT:-5432}"
DB_NAME="${PGDATABASE:-golteris}"
DB_USER="${PGUSER:-golteris}"
BACKUP_DIR="${BACKUP_DIR:-./backups}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"

# Timestamp for the backup filename
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/golteris_${TIMESTAMP}.sql.gz"

echo "[$(date -Iseconds)] Starting backup of ${DB_NAME}@${DB_HOST}:${DB_PORT}"

# Create backup directory if it doesn't exist
mkdir -p "${BACKUP_DIR}"

# Run pg_dump with compression
# Uses custom format (-Fc) for parallel restore capability
pg_dump \
  -h "${DB_HOST}" \
  -p "${DB_PORT}" \
  -U "${DB_USER}" \
  -d "${DB_NAME}" \
  --no-owner \
  --no-privileges \
  -Fc \
  -f "${BACKUP_FILE}"

# Verify the backup file was created and has content
if [ -s "${BACKUP_FILE}" ]; then
  SIZE=$(du -h "${BACKUP_FILE}" | cut -f1)
  echo "[$(date -Iseconds)] Backup complete: ${BACKUP_FILE} (${SIZE})"
else
  echo "[$(date -Iseconds)] ERROR: Backup file is empty or missing"
  exit 1
fi

# Prune old backups beyond retention period
PRUNED=$(find "${BACKUP_DIR}" -name "golteris_*.sql.gz" -mtime +${RETENTION_DAYS} -delete -print | wc -l)
if [ "${PRUNED}" -gt 0 ]; then
  echo "[$(date -Iseconds)] Pruned ${PRUNED} backups older than ${RETENTION_DAYS} days"
fi

echo "[$(date -Iseconds)] Backup job complete"
