#!/usr/bin/env bash
# 80: Prepares sub-<client> and deploys the client's shared stack (VNet, prod and nonprod Postgres, Container Apps
# environments, Key Vaults, db-ops jobs). Create the subscription in the portal first and set subscription_id in
# registry/clients/<client>.yaml. The client stack renders only once the client has a graduated app.
#
#   bootstrap/80-onboard-client.sh <client>
# Needs: Owner on mg-blufire.
source "$(dirname "$0")/lib.sh"

client="${1:-}"
[[ -n "$client" ]] || die "usage: $0 <client>"
file="registry/clients/$client.yaml"
[[ -f "$file" ]] || die "$file not found"
sub="$(python3 -c 'import yaml,sys; print(yaml.safe_load(open(sys.argv[1])).get("subscription_id") or "")' "$file")"
[[ -n "$sub" ]] || die "$file has no subscription_id"

log "Subscription $sub under $(cfg management_group)"
add_to_management_group "$sub"
register_providers "$sub"

if python3 tools/render_params.py --out build/params >/dev/null && [[ -f "build/params/client-$client.json" ]]; then
  deploy --only "client:$client"
  deploy --only backup
  echo "Client stack deployed for $client."
else
  echo "No graduated app for $client yet: subscription prepared, stack not deployed."
fi
