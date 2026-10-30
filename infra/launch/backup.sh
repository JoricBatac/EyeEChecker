#!/usr/bin/env bash
# Nightly encrypted Postgres dump to a separate bucket prefix (PRD 12.7). The database contains no photos.
# Requires in .env: BACKUP_PASSPHRASE, BACKUP_BUCKET, STORAGE_ACCESS_KEY, STORAGE_SECRET_KEY.
# Set a 30-day lifecycle rule on the backups/ prefix in the bucket.
set -euo pipefail

stamp=$(date -u +%Y%m%d-%H%M%S)
file="/tmp/scanassist-${stamp}.sql.gz.gpg"

pg_dump -h postgres -U scanassist scanassist \
  | gzip \
  | gpg --batch --yes --symmetric --cipher-algo AES256 --passphrase "${BACKUP_PASSPHRASE}" -o "${file}"

# Upload with the S3-compatible XML API (HMAC keys) using AWS SigV4 via curl.
key="backups/$(basename "${file}")"
curl -sS --fail --aws-sigv4 "aws:amz:asia-southeast1:s3" \
  --user "${STORAGE_ACCESS_KEY}:${STORAGE_SECRET_KEY}" \
  -H "x-amz-content-sha256: UNSIGNED-PAYLOAD" \
  -T "${file}" "https://storage.googleapis.com/${BACKUP_BUCKET}/${key}"

rm -f "${file}"
echo "$(date -u) backup uploaded: ${key}"
