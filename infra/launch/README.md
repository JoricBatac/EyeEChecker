# Launch stack (Phase 0 to 1)

One Oracle Cloud Always Free ARM VM (Ampere A1, 4 OCPU / 24 GB) in **ap-singapore-1**, plus a private
GCS bucket in **asia-southeast1** for photos. Approx. $0 to $5 per month.

## One-time setup

1. **Bucket** (Google Cloud, Blaze plan, $5 budget alert):
   - Create bucket `scanassist-photos-prod`, location `asia-southeast1`, uniform access, public access prevention on.
   - Lifecycle rule: delete objects older than 7 days (safety net, PRD 11.1).
   - Second bucket (or prefix) for backups with a 30-day delete rule.
   - Settings > Interoperability: create an HMAC key for a service account with Storage Object Admin on both.
2. **VM**: Ubuntu 22.04 aarch64, open ports 80/443 in the security list, install Docker + compose plugin.
3. Point DNS `API_DOMAIN` at the VM's public IP.
4. On the VM:
   ```
   git clone https://github.com/JoricBatac/EyeEChecker.git && cd EyeEChecker/infra/launch
   cp .env.example .env && nano .env
   docker compose up -d --build
   docker compose exec backend python -m scripts.init_db
   ```
5. Create the internal admin account (first login enrolls MFA):
   ```
   docker compose exec backend python -c "from scripts.bootstrap_admin import run; run('you@domain', 'Your Name')"
   ```

The backend refuses to start in production unless storage is `asia-southeast1`, secrets are set and the
database is Postgres.

## Restore a backup

```
gpg --decrypt scanassist-YYYYMMDD.sql.gz.gpg | gunzip | psql -h localhost -U scanassist scanassist
```
