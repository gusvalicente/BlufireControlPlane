#!/usr/bin/env bash
# Helper for 85 and 90: puts <app>-auth-secret and <app>-entra-client-secret into a vault if missing.
#   bootstrap/lib-app-secrets.sh <vault> <app> <entra-app-id> <subscription>
source "$(dirname "$0")/lib.sh"

kv="$1" app="$2" entra="$3" sub="$4"
kv_id="$(az keyvault show --name "$kv" --subscription "$sub" --query id -o tsv)"
az role assignment create --assignee "$(signed_in_object_id)" --role "Key Vault Secrets Officer" --scope "$kv_id" \
  -o none --only-show-errors
sleep 30
has() { az keyvault secret show --vault-name "$kv" --name "$1" -o none 2>/dev/null; }
has "$app-auth-secret" || az keyvault secret set --vault-name "$kv" --name "$app-auth-secret" \
  --value "$(openssl rand -base64 32)" -o none
if ! has "$app-entra-client-secret"; then
  secret="$(az ad app credential reset --id "$entra" --append --display-name "$kv" --years 1 --query password -o tsv)"
  az keyvault secret set --vault-name "$kv" --name "$app-entra-client-secret" --value "$secret" -o none
  unset secret
fi
echo "Secrets ready in $kv for $app."
