#!/usr/bin/env bash
# 30: Creates the Entra app registrations and records their IDs in infra/platform-settings.json.
#
#   bootstrap/30-entra-app-registrations.sh                     platform-api, admin UI, MCP (idempotent)
#   bootstrap/30-entra-app-registrations.sh rotate-mcp-secret   new secret for the Claude connector
#   bootstrap/30-entra-app-registrations.sh client-app <client> <app> [frontend-host]
#                                                               multi-tenant registration for one client app
#
# platform-api: app roles Admin (users) and Agent (applications), delegated scope access_as_user.
# admin UI:     confidential web client of platform-api. Its client secret is created by 60 straight into Key Vault.
# MCP:          Application ID URI https://<domains.mcp>/mcp (needs that domain verified in Entra), delegated scope
#               access_as_user, Claude's OAuth callback, http://localhost:8765/callback for Claude Code
#               (claude mcp add ... --callback-port 8765), user assignment required
#               with only you assigned. Its client secret is printed once for Claude's connector settings.
# Needs: Application Administrator (or Global Administrator) in the BluFire tenant.
source "$(dirname "$0")/lib.sh"
require_cmd az jq python3

GRAPH=https://graph.microsoft.com/v1.0

app_id_by_name() { az ad app list --display-name "$1" --query '[0].appId' -o tsv; }
object_id_of_app() { az ad app show --id "$1" --query id -o tsv; }
uuid() { python3 -c 'import uuid; print(uuid.uuid4())'; }

ensure_sp() {
  az ad sp show --id "$1" -o none 2>/dev/null || az ad sp create --id "$1" -o none
  sp_object_id "$1"
}

# Adds a delegated scope access_as_user to an app if it has none. Sets v2 access tokens.
ensure_scope() {
  local app_id="$1" label="$2" obj existing
  obj="$(object_id_of_app "$app_id")"
  existing="$(az ad app show --id "$app_id" --query "api.oauth2PermissionScopes[?value=='access_as_user'].id | [0]" -o tsv)"
  if [[ -z "$existing" ]]; then
    existing="$(uuid)"
    az rest --method PATCH --uri "$GRAPH/applications/$obj" --headers Content-Type=application/json --body "{
      \"api\": {
        \"requestedAccessTokenVersion\": 2,
        \"oauth2PermissionScopes\": [{
          \"id\": \"$existing\", \"value\": \"access_as_user\", \"type\": \"User\", \"isEnabled\": true,
          \"adminConsentDisplayName\": \"Access $label as the signed-in user\",
          \"adminConsentDescription\": \"Allows the app to call $label on behalf of the signed-in user.\",
          \"userConsentDisplayName\": \"Access $label\",
          \"userConsentDescription\": \"Allows the app to call $label on your behalf.\"
        }]
      }
    }"
  fi
  echo "$existing"
}

assign_app_role() { # resource-sp-object-id principal-object-id app-role-id
  local exists
  exists="$(az rest --method GET --uri "$GRAPH/servicePrincipals/$1/appRoleAssignedTo" \
    --query "value[?principalId=='$2' && appRoleId=='$3'] | length(@)" -o tsv)"
  [[ "$exists" != "0" ]] && return 0
  az rest --method POST --uri "$GRAPH/servicePrincipals/$1/appRoleAssignedTo" --headers Content-Type=application/json \
    --body "{\"principalId\":\"$2\",\"resourceId\":\"$1\",\"appRoleId\":\"$3\"}" -o none
}

platform() {
  local me audience api_id api_sp scope_id ui_id ui_host mcp_id mcp_host mcp_sp admin_role created_mcp=0
  me="$(signed_in_object_id)"
  audience="$(setting apiAudience)"

  log "platform-api ($audience)"
  api_id="$(app_id_by_name blufire-platform-api)"
  if [[ -z "$api_id" ]]; then
    roles="$(mktemp)"
    cat > "$roles" <<JSON
[
  {"allowedMemberTypes": ["User"], "displayName": "Admin", "value": "Admin", "isEnabled": true,
   "description": "Full control of the BluFire platform through the admin UI", "id": "$(uuid)"},
  {"allowedMemberTypes": ["Application"], "displayName": "Agent", "value": "Agent", "isEnabled": true,
   "description": "MCP server: read, safe operations and change proposals only", "id": "$(uuid)"}
]
JSON
    api_id="$(az ad app create --display-name blufire-platform-api --sign-in-audience AzureADMyOrg \
      --identifier-uris "$audience" --app-roles "@$roles" --query appId -o tsv)"
    rm -f "$roles"
  fi
  scope_id="$(ensure_scope "$api_id" "BluFire platform API")"
  api_sp="$(ensure_sp "$api_id")"
  admin_role="$(az ad app show --id "$api_id" --query "appRoles[?value=='Admin'].id | [0]" -o tsv)"
  assign_app_role "$api_sp" "$me" "$admin_role"

  log "Admin UI"
  ui_host="$(cfg domains.admin_ui)"
  ui_id="$(app_id_by_name blufire-admin-ui)"
  if [[ -z "$ui_id" ]]; then
    ui_id="$(az ad app create --display-name blufire-admin-ui --sign-in-audience AzureADMyOrg \
      ${ui_host:+--web-redirect-uris "https://$ui_host/api/auth/callback/microsoft-entra-id"} \
      --optional-claims '{"idToken":[{"name":"auth_time","essential":false}]}' \
      --query appId -o tsv)"
  fi
  az ad app permission add --id "$ui_id" --api "$api_id" --api-permissions "$scope_id=Scope" -o none 2>/dev/null || true
  ensure_sp "$ui_id" >/dev/null
  az ad app permission admin-consent --id "$ui_id" -o none || echo "note: grant admin consent for blufire-admin-ui in the portal"

  log "MCP"
  mcp_host="$(cfg domains.mcp)"
  [[ "$mcp_host" == *REPLACE* ]] && die "set domains.mcp in platform.yaml and verify the domain in Entra first"
  mcp_id="$(app_id_by_name blufire-mcp)"
  if [[ -z "$mcp_id" ]]; then
    mcp_id="$(az ad app create --display-name blufire-mcp --sign-in-audience AzureADMyOrg \
      --identifier-uris "https://$mcp_host/mcp" \
      --web-redirect-uris "https://claude.ai/api/mcp/auth_callback" "http://localhost:8765/callback" \
      --query appId -o tsv)"
    created_mcp=1
  fi
  ensure_scope "$mcp_id" "BluFire MCP" >/dev/null
  mcp_sp="$(ensure_sp "$mcp_id")"
  az ad sp update --id "$mcp_id" --set appRoleAssignmentRequired=true
  assign_app_role "$mcp_sp" "$me" "00000000-0000-0000-0000-000000000000"

  setting_set uiClientId "\"$ui_id\""
  # v2 access tokens carry the app's client id as aud, so platform-api accepts both forms.
  setting_set apiClientId "\"$api_id\""
  setting_set mcpClientId "\"$mcp_id\""
  setting_set adminObjectId "\"$me\""

  if [[ "$created_mcp" == 1 ]]; then rotate_mcp_secret; fi
  log "Recorded in infra/platform-settings.json: apiClientId, uiClientId, mcpClientId, adminObjectId. Commit that file."
}

rotate_mcp_secret() {
  local mcp_id secret
  mcp_id="$(app_id_by_name blufire-mcp)"
  [[ -n "$mcp_id" ]] || die "run this script without arguments first"
  secret="$(az ad app credential reset --id "$mcp_id" --append --display-name claude-connector --years 1 \
    --query password -o tsv)"
  cat <<TXT

Claude custom connector (Settings > Connectors > Add custom connector > Advanced settings):
  URL:           https://$(cfg domains.mcp)/mcp
  Client ID:     $mcp_id
  Client secret: $secret
This secret is shown once and is not stored anywhere else. It expires in 1 year.
TXT
}

client_app() {
  local client="$1" app="$2" host="${3:-}" name="blufire-$1-$2" id
  [[ -n "$client" && -n "$app" ]] || die "usage: $0 client-app <client> <app> [frontend-host]"
  log "Multi-tenant registration $name"
  id="$(app_id_by_name "$name")"
  if [[ -z "$id" ]]; then
    id="$(az ad app create --display-name "$name" --sign-in-audience AzureADMultipleOrgs \
      ${host:+--web-redirect-uris "https://$host/api/auth/callback/microsoft-entra-id"} --query appId -o tsv)"
    az ad app update --id "$id" --identifier-uris "api://$id"
  elif [[ -n "$host" ]]; then
    az ad app update --id "$id" --web-redirect-uris "https://$host/api/auth/callback/microsoft-entra-id"
  fi
  ensure_scope "$id" "$name" >/dev/null
  ensure_sp "$id" >/dev/null
  tenant="$(python3 -c 'import yaml,sys; print(yaml.safe_load(open(sys.argv[1]))["tenant_id"])' "registry/clients/$client.yaml")"
  cat <<TXT

Set in registry/apps/$client/$app.yaml:  auth.entra_app_id: $id
Send the client's Microsoft 365 admin this consent link:
  https://login.microsoftonline.com/$tenant/adminconsent?client_id=$id
After they approve, set auth.consent_granted: true.
TXT
}

case "${1:-}" in
  "") platform ;;
  rotate-mcp-secret) rotate_mcp_secret ;;
  client-app) shift; client_app "$@" ;;
  *) die "unknown command: $1" ;;
esac
