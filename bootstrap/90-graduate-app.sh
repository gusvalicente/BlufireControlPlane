#!/usr/bin/env bash
# 90: Finishes a graduation after the graduation PR (stage: graduated, client subscription_id set) is merged:
#   1. client stack (80), 2. app secrets in kv-<c>-prod and kv-<c>-nonprod, 3. app environments,
#   4. database roles for each app identity (db-ops grant), 5. removes the app's sandbox databases and resource group.
#
#   bootstrap/90-graduate-app.sh <client> <app> [--keep-sandbox]
source "$(dirname "$0")/lib.sh"

client="${1:-}" app="${2:-}" keep="${3:-}"
[[ -n "$client" && -n "$app" ]] || die "usage: $0 <client> <app> [--keep-sandbox]"
file="registry/apps/$client/$app.yaml"
stage="$(python3 -c 'import yaml,sys; print(yaml.safe_load(open(sys.argv[1]))["stage"])' "$file")"
[[ "$stage" == "graduated" ]] || die "$file is still $stage; merge the graduation PR first"
entra="$(python3 -c 'import yaml,sys; print(yaml.safe_load(open(sys.argv[1]))["auth"].get("entra_app_id") or "")' "$file")"
[[ -n "$entra" ]] || die "$file has no auth.entra_app_id (create it with 30-entra-app-registrations.sh client-app)"
sub="$(python3 -c 'import yaml,sys; print(yaml.safe_load(open(sys.argv[1]))["subscription_id"])' "registry/clients/$client.yaml")"

bootstrap/80-onboard-client.sh "$client"
for tier in prod nonprod; do
  vault="$(python3 -c 'import sys; sys.path.insert(0, "tools"); import render_params as r
print(r.client_names(sys.argv[1], sys.argv[2])["keyVault"][sys.argv[3]])' "$client" "$sub" "$tier")"
  bootstrap/lib-app-secrets.sh "$vault" "$app" "$entra" "$sub"
done

deploy --only "app:$client/$app"

log "Database roles"
for env in dev cert prod; do
  params="build/params/app-$client-$app-$env.json"
  [[ -f "$params" ]] || { echo "  $env not deployed yet (no images); grant later"; continue; }
  tier=$([[ "$env" == prod ]] && echo prod || echo nonprod)
  db="$(jq -r .parameters.databaseName.value "$params")"
  principal="$(jq -r .parameters.identityName.value "$params")"
  job="caj-$client-dbops-$tier"
  exec_name="$(start_dbops "$sub" "rg-$client-shared" "$job" grant --database "$db" --principal "$principal")"
  echo "  $env: grant started ($exec_name); check: az containerapp job execution show -n $job -g rg-$client-shared --job-execution-name $exec_name"
done

if [[ "$keep" != "--keep-sandbox" ]]; then
  log "Sandbox cleanup"
  ssub="$(cfg subscriptions.sandbox)"
  sandbox_pg="$(python3 tools/render_params.py --names | jq -r .sandbox.postgres)"
  for env in dev cert prod; do
    db="$(echo "${client}_${app}_${env}" | tr '-' '_')"
    az postgres flexible-server db delete --resource-group rg-sandbox-shared --server-name "$sandbox_pg" \
      --database-name "$db" --subscription "$ssub" --yes -o none 2>/dev/null && echo "  dropped $db" || true
  done
  az group delete --name "rg-sandbox-$client-$app" --subscription "$ssub" --yes --no-wait 2>/dev/null \
    && echo "  deleting rg-sandbox-$client-$app" || true
  echo "  Sandbox PITR copies expire within 7 days."
fi

tenant="$(python3 -c 'import yaml,sys; print(yaml.safe_load(open(sys.argv[1]))["tenant_id"])' "registry/clients/$client.yaml")"
cat <<TXT

Graduated $client/$app. If consent is not granted yet, send the client's admin:
  https://login.microsoftonline.com/$tenant/adminconsent?client_id=$entra
TXT
