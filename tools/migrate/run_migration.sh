#!/usr/bin/env bash
# Restore an uploaded Supabase export into the app's Azure database through its db-ops job, then verify.
# Usage: tools/migrate/run_migration.sh <app-id> <env> <prefix printed by export_from_supabase.sh> [--seed-identities]
# Needs: az CLI signed in with rights to start the db-ops job, jq, python3 with pyyaml (pip install pyyaml).
set -euo pipefail

APP="${1:?app}"; ENV="${2:?env}"; PREFIX="${3:?prefix}"
read -r SUB RG JOB DB IDENTITY < <(python3 - "$APP" "$ENV" <<'PY'
import glob, sys, yaml
app_id, env = sys.argv[1], sys.argv[2]
platform = yaml.safe_load(open("platform.yaml"))
app = next(yaml.safe_load(open(p)) for p in glob.glob("registry/apps/*/*.yaml") if yaml.safe_load(open(p))["id"] == app_id)
client = yaml.safe_load(open(f"registry/clients/{app['client']}.yaml"))
c, a = app["client"], app["id"]
if app["stage"] == "incubating":
    print(platform["subscriptions"]["sandbox"], "rg-sandbox-shared", "caj-sandbox-dbops", f"{c}_{a}_{env}".replace("-", "_"), f"id-{c}-{a}-{env}")
else:
    tier = "prod" if env == "prod" else "nonprod"
    print(client["subscription_id"], f"rg-{c}-shared", f"caj-{c}-dbops-{tier}", f"{a}_{env}".replace("-", "_"), f"id-{c}-{a}-{env}")
PY
)

run() {
  local args_json; args_json="$(printf '%s\n' "$@" | jq -R . | jq -s .)"
  local base="https://management.azure.com/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.App/jobs/$JOB"
  local container; container="$(az rest --method get --uri "$base?api-version=2024-03-01" --query 'properties.template.containers[0]' -o json)"
  local body; body="$(jq -n --argjson c "$container" --argjson a "$args_json" '{containers: [($c + {args: $a})]}')"
  local exec_name; exec_name="$(az rest --method post --uri "$base/start?api-version=2024-03-01" --body "$body" --query name -o tsv)"
  echo "   started $JOB execution $exec_name: $*"
  while true; do
    sleep 10
    local status; status="$(az containerapp job execution show -n "$JOB" -g "$RG" --subscription "$SUB" --job-execution-name "$exec_name" --query properties.status -o tsv)"
    case "$status" in
      Succeeded) echo "   done"; return 0 ;;
      Failed|Stopped|Degraded) echo "   $status: check logs with: az containerapp job logs show -n $JOB -g $RG --execution $exec_name"; return 1 ;;
    esac
  done
}

if [[ "${4:-}" == "--seed-identities" ]]; then
  echo "seeding identity_map from $PREFIX/identity_map.sql"
  run run-sql --app "$APP" --env "$ENV" --database "$DB" --blob "$PREFIX/identity_map.sql"
  exit 0
fi

echo "1/3 create database $DB and grant $IDENTITY"
run grant --app "$APP" --env "$ENV" --database "$DB" --principal "$IDENTITY"
echo "2/3 restore $PREFIX/app.dump (skipping Supabase RLS policies and extensions)"
run migrate-from-blob --app "$APP" --env "$ENV" --database "$DB" --blob "$PREFIX/app.dump" --skip-supabase-objects
echo "3/3 verify row counts"
run verify --app "$APP" --env "$ENV" --database "$DB" --expect "$PREFIX/expected_counts.json"

cat <<NEXT

Data is in Azure and row counts match. Remaining steps (docs/sop/migrate-from-supabase.md):
  - deploy the app (its migrations create identity_map)
  - seed identity links:  tools/migrate/run_migration.sh $APP $ENV $PREFIX --seed-identities
NEXT
