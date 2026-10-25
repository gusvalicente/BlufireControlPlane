#!/usr/bin/env bash
# 20: Assigns the Azure Policy baseline at mg-blufire (built-ins looked up by display name, no hardcoded IDs),
# defines the custom what-if role used by CI, and reports Defender for Cloud status.
# Defender Foundational CSPM is free and on by default; nothing paid is enabled here.
# Needs: Owner on mg-blufire.
source "$(dirname "$0")/lib.sh"

mg="$(cfg management_group)"
scope="/providers/Microsoft.Management/managementGroups/$mg"
region="$(cfg region)"

policy_id() {
  local id
  id="$(az policy definition list --query "[?displayName=='$1' && policyType=='BuiltIn'].id | [0]" -o tsv)"
  [[ -n "$id" ]] || die "built-in policy not found: '$1'. Search with: az policy definition list --query \"[?contains(displayName,'$2')].displayName\""
  echo "$id"
}

assign() { # name, display, definitionId, params-json, enforcement (Default | DoNotEnforce)
  if az policy assignment show --name "$1" --scope "$scope" -o none 2>/dev/null; then
    echo "  exists: $1"
  else
    az policy assignment create --name "$1" --display-name "$2" --scope "$scope" --policy "$3" \
      ${4:+--params "$4"} --enforcement-mode "${5:-Default}" -o none
    echo "  assigned: $1"
  fi
}

log "Policy baseline at $mg"
assign bf-allowed-locations "BluFire: allowed locations" "$(policy_id 'Allowed locations' 'locations')" \
  "{\"listOfAllowedLocations\":{\"value\":[\"$region\"]}}"

# Report-only: Azure creates untagged resource groups of its own (for example the ME_* group behind every
# Container Apps environment), and a deny here would block them. Bicep tags everything it creates.
rg_tag="$(policy_id 'Require a tag on resource groups' 'tag on resource groups')"
for tag in client app env managed-by; do
  assign "bf-rg-tag-$tag" "BluFire: resource groups need tag $tag" "$rg_tag" "{\"tagName\":{\"value\":\"$tag\"}}" DoNotEnforce
done

pg_public="$(az policy definition list --query "[?policyType=='BuiltIn' && contains(displayName,'PostgreSQL flexible servers') && contains(displayName,'Public network access')].id | [0]" -o tsv)"
if [[ -n "$pg_public" ]]; then
  effect="$(az policy definition show --name "${pg_public##*/}" --query "parameters.effect.allowedValues" -o tsv | tr '\t' '\n' | grep -m1 -x Deny || true)"
  assign bf-pg-no-public "BluFire: Postgres flexible public access disabled" "$pg_public" \
    ${effect:+"{\"effect\":{\"value\":\"Deny\"}}"}
else
  echo "warning: built-in 'Public network access should be disabled for PostgreSQL flexible servers' not found; Bicep already disables it"
fi

log "Custom role: BluFire What-If (read + validate/what-if, for pull request checks)"
if [[ -z "$(az role definition list --name 'BluFire What-If' --scope "$scope" --query '[0].id' -o tsv)" ]]; then
  az role definition create --role-definition "{
    \"Name\": \"BluFire What-If\",
    \"Description\": \"Read everything and run deployment validate/what-if. Cannot change resources.\",
    \"Actions\": [\"*/read\", \"Microsoft.Resources/deployments/validate/action\", \"Microsoft.Resources/deployments/whatIf/action\"],
    \"AssignableScopes\": [\"$scope\"]
  }" -o none
fi

log "Defender for Cloud (Foundational CSPM is free; paid plans stay off)"
for s in platform backup sandbox; do
  sub="$(cfg subscriptions.$s)"
  az security pricing show --name CloudPosture --subscription "$sub" --query '{plan:name, tier:pricingTier}' -o tsv || true
done
email="$(cfg alerts.email)"
az security contact create --name default --email "$email" --alert-notifications '{"state":"On","minimalSeverity":"High"}' \
  --notifications-by-role '{"state":"On","roles":["Owner"]}' --subscription "$(cfg subscriptions.platform)" -o none 2>/dev/null \
  || echo "note: set the Defender security contact in the portal if this CLI version lacks 'az security contact create'"
echo "done"
