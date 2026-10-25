#!/usr/bin/env bash
# 00: Checks local tools, Azure sign-in and the tenant before anything is created. Changes nothing.
# Needs: az CLI (with Bicep), python3 with pyyaml + jsonschema, jq, git, openssl. Optional: gh.
source "$(dirname "$0")/lib.sh"

require_cmd az python3 jq git openssl
python3 -c 'import yaml, jsonschema' || die "pip install pyyaml jsonschema"
az bicep version >/dev/null 2>&1 || az bicep install

log "Azure sign-in"
az account show --query '{user:user.name, tenant:tenantId}' -o table || die "run: az login --tenant <tenant-id>"
tenant="$(az account show --query tenantId -o tsv)"
want="$(cfg tenant_id)"
[[ "$tenant" == "$want" ]] || die "signed into tenant $tenant but platform.yaml tenant_id is $want"

log "platform.yaml values"
require_set tenant_id subscriptions.platform subscriptions.backup subscriptions.sandbox \
  github.org network.admin_static_ip alerts.email postgres.entra_admin_group_object_id
for d in domains.admin_ui domains.mcp; do
  [[ "$(cfg "$d")" == *REPLACE* ]] && echo "warning: $d not set; the MCP connector and UI custom domain need it"
done

log "Subscriptions visible"
for s in platform backup sandbox; do
  az account show --subscription "$(cfg subscriptions.$s)" --query name -o tsv || die "cannot see $s subscription"
done

log "Registry renders"
python3 tools/render_params.py --check
echo "ok"
