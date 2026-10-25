#!/usr/bin/env bash
# Export one app's database from Supabase and upload it for the Azure db-ops job to restore.
# Run on Gus's MacBook from the static IP (the backup storage firewall only allows that IP).
#
# Usage: SUPABASE_DB_URL='postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres' \
#        tools/migrate/export_from_supabase.sh <app-id> [env] [schemas]
#   env      default prod
#   schemas  comma-separated, default public
# Needs: pg_dump/psql 17 (brew install postgresql@17), az CLI signed in (az login), jq, python3 with pyyaml.
set -euo pipefail

APP="${1:?app id required}"; ENV="${2:-prod}"; SCHEMAS="${3:-public}"
: "${SUPABASE_DB_URL:?set SUPABASE_DB_URL to the Supabase session pooler connection string}"
ACCOUNT="${BACKUP_STORAGE_ACCOUNT:-$(python3 tools/render_params.py --names 2>/dev/null | jq -r .backupStorage)}"
: "${ACCOUNT:?set BACKUP_STORAGE_ACCOUNT}"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="$(mktemp -d)"; trap 'rm -rf "$OUT"' EXIT
PREFIX="$APP/$ENV/$STAMP"
SCHEMA_ARGS=(); SCHEMA_LIST=""
IFS=',' read -ra PARTS <<< "$SCHEMAS"
for s in "${PARTS[@]}"; do SCHEMA_ARGS+=(-n "$s"); SCHEMA_LIST+="'$s',"; done
SCHEMA_LIST="${SCHEMA_LIST%,}"

echo "1/4 dumping schemas [$SCHEMAS] from Supabase"
pg_dump "$SUPABASE_DB_URL" -Fc --no-owner --no-privileges "${SCHEMA_ARGS[@]}" -f "$OUT/app.dump"

echo "2/4 counting rows for verification"
psql "$SUPABASE_DB_URL" -At -v ON_ERROR_STOP=1 -c "
  select n.nspname || '.' || c.relname from pg_class c join pg_namespace n on n.oid = c.relnamespace
  where c.relkind = 'r' and n.nspname in ($SCHEMA_LIST) order by 1" > "$OUT/tables.txt"
python3 - "$OUT" "$SUPABASE_DB_URL" <<'PY'
import json, subprocess, sys
out, url = sys.argv[1], sys.argv[2]
counts = {}
for t in open(f"{out}/tables.txt").read().split():
    schema, table = t.split(".", 1)
    ident = ".".join('"' + p.replace('"', '""') + '"' for p in (schema, table))
    counts[t] = int(subprocess.run(["psql", url, "-At", "-c", f"select count(*) from {ident}"],
                                   capture_output=True, text=True, check=True).stdout.strip())
json.dump(counts, open(f"{out}/expected_counts.json", "w"), indent=2)
print(f"   {len(counts)} tables, {sum(counts.values())} rows")
PY

echo "3/4 building identity_map seed from auth.users (email and old user id only)"
psql "$SUPABASE_DB_URL" -At -v ON_ERROR_STOP=1 -c "
  select format('insert into identity_map(supabase_user_id, email) values (%L, %L) on conflict do nothing;', id, lower(email))
  from auth.users where email is not null" > "$OUT/identity_map.sql"
echo "   $(wc -l < "$OUT/identity_map.sql" | tr -d ' ') users"

echo "4/4 uploading to $ACCOUNT/migrations/$PREFIX/"
for f in app.dump expected_counts.json identity_map.sql; do
  az storage blob upload --auth-mode login --account-name "$ACCOUNT" --container-name migrations \
    --name "$PREFIX/$f" --file "$OUT/$f" --only-show-errors >/dev/null
done

cat <<NEXT

Uploaded. Next (see docs/sop/migrate-from-supabase.md):
  tools/migrate/run_migration.sh $APP $ENV $PREFIX
NEXT
