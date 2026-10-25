#!/usr/bin/env bash
# 60: Deploys sub-blufire-platform in passes:
#   1. core resources (registry, Key Vault, Log Analytics + Sentinel, state Postgres, email) without apps
#   2. Key Vault secrets, then builds the three control plane images in ACR (no local Docker needed)
#   3. the api, ui, mcp apps and worker jobs
#   4. custom domains, after you create the DNS records it prints
# then grants the platform identity its tenant-wide roles and the Agent app role, and updates the backup firewall.
#
#   bootstrap/60-deploy-platform.sh --github-app-key <path-to.pem> [--skip-build] [--domains-only]
# Needs: 30 and 40 done, Owner on mg-blufire (role assignments), Application Administrator (app role).
source "$(dirname "$0")/lib.sh"
require_cmd az jq openssl git

key_file="" skip_build=0 domains_only=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --github-app-key) key_file="$2"; shift 2 ;;
    --skip-build) skip_build=1; shift ;;
    --domains-only) domains_only=1; shift ;;
    *) die "unknown argument: $1" ;;
  esac
done

psub="$(cfg subscriptions.platform)"
prg="$(name resourceGroup)"
kv="$(name keyVault)"
acr="$(name acr)"
out() { az deployment sub show --name bf-platform --subscription "$psub" --query "properties.outputs.$1.value" -o tsv; }

bind_domains() {
  log "Custom domains"
  ver="$(out customDomainVerificationId)"
  ui_fqdn="$(out uiFqdn)"; mcp_fqdn="$(out mcpFqdn)"
  cat <<TXT
Create these DNS records at your DNS provider:
  CNAME  $(cfg domains.admin_ui)          -> $ui_fqdn
  TXT    asuid.$(cfg domains.admin_ui)    -> $ver
  CNAME  $(cfg domains.mcp)               -> $mcp_fqdn
  TXT    asuid.$(cfg domains.mcp)         -> $ver
TXT
  read -r -p "Press Enter once the records resolve (check with: dig +short CNAME $(cfg domains.mcp)) " _
  deploy --only platform
  echo "Custom domains bound with managed certificates."
}

if [[ "$domains_only" == 1 ]]; then bind_domains; exit 0; fi
[[ -n "$(setting uiClientId)" && -n "$(setting mcpClientId)" ]] || die "run 30-entra-app-registrations.sh first"
[[ -n "$key_file" || "$skip_build" == 1 ]] || die "pass --github-app-key <pem> (the GitHub App's private key)"

log "Pass 1: core resources"
deploy --only platform --set deployApps=false --set bindCustomDomains=false
principal="$(out identityPrincipalId)"
setting_set platformPrincipalId "\"$principal\""

log "Key Vault secrets ($kv)"
me="$(signed_in_object_id)"
kv_id="$(az keyvault show --name "$kv" --subscription "$psub" --query id -o tsv)"
az role assignment create --assignee "$me" --role "Key Vault Secrets Officer" --scope "$kv_id" -o none --only-show-errors
sleep 30  # role assignment propagation
has_secret() { az keyvault secret show --vault-name "$kv" --name "$1" -o none 2>/dev/null; }
has_secret heartbeat-token || az keyvault secret set --vault-name "$kv" --name heartbeat-token --value "$(openssl rand -hex 32)" -o none
has_secret ui-auth-secret || az keyvault secret set --vault-name "$kv" --name ui-auth-secret --value "$(openssl rand -base64 32)" -o none
if ! has_secret ui-entra-client-secret; then
  secret="$(az ad app credential reset --id "$(setting uiClientId)" --append --display-name admin-ui --years 1 --query password -o tsv)"
  az keyvault secret set --vault-name "$kv" --name ui-entra-client-secret --value "$secret" -o none
  unset secret
fi
[[ -n "$key_file" ]] && az keyvault secret set --vault-name "$kv" --name github-app-private-key --file "$key_file" -o none
echo "Set heartbeat-token on the Mac Mini later: az keyvault secret show --vault-name $kv --name heartbeat-token --query value -o tsv"

if [[ "$skip_build" == 0 ]]; then
  log "Building control plane images in $acr"
  tag="$(git rev-parse --short HEAD)"
  build() { # image dockerfile context
    az acr build --registry "$acr" --subscription "$psub" --image "$1:$tag" --file "$2" "$3" --only-show-errors -o none
    digest="$(az acr repository show --name "$acr" --subscription "$psub" --image "$1:$tag" --query digest -o tsv)"
    echo "$acr.azurecr.io/$1@$digest"
  }
  cp_img="$(build blufire-control-plane control-plane/Dockerfile control-plane)"
  ui_img="$(build blufire-ui control-plane/ui/Dockerfile control-plane/ui)"
  db_img="$(build blufire-dbops control-plane/dbops/Dockerfile control-plane)"
  python3 - "$cp_img" "$ui_img" "$db_img" <<'PY'
import json, sys
path = "infra/platform-images.json"
data = json.load(open(path))
data.update(controlPlane=sys.argv[1], ui=sys.argv[2], dbops=sys.argv[3])
open(path, "w").write(json.dumps(data, indent=2) + "\n")
PY
fi

log "Pass 2: apps and worker jobs"
deploy --only platform --set bindCustomDomains=false

log "Platform identity roles on $(cfg management_group)"
mg_scope="/providers/Microsoft.Management/managementGroups/$(cfg management_group)"
for role in "Reader" "Cost Management Reader"; do
  az role assignment create --assignee-object-id "$principal" --assignee-principal-type ServicePrincipal \
    --role "$role" --scope "$mg_scope" -o none --only-show-errors
done

log "Agent app role for the platform identity (MCP server calls the API as Agent)"
api_sp="$(az ad sp list --display-name blufire-platform-api --query '[0].id' -o tsv)"
agent_role="$(az ad sp show --id "$api_sp" --query "appRoles[?value=='Agent'].id | [0]" -o tsv)"
already="$(az rest --method GET --uri "https://graph.microsoft.com/v1.0/servicePrincipals/$api_sp/appRoleAssignedTo" \
  --query "value[?principalId=='$principal'] | length(@)" -o tsv)"
[[ "$already" != "0" ]] || az rest --method POST \
  --uri "https://graph.microsoft.com/v1.0/servicePrincipals/$api_sp/appRoleAssignedTo" \
  --headers Content-Type=application/json \
  --body "{\"principalId\":\"$principal\",\"resourceId\":\"$api_sp\",\"appRoleId\":\"$agent_role\"}" -o none

log "Backup firewall: admit the platform subnet"
deploy --only backup

bind_domains

cat <<TXT

Platform deployed. Commit infra/platform-settings.json and infra/platform-images.json.
Admin UI: https://$(cfg domains.admin_ui)   MCP: https://$(cfg domains.mcp)/mcp
TXT
