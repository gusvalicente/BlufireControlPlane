#!/usr/bin/env bash
# 10: Creates mg-blufire, moves the platform, backup and sandbox subscriptions under it and registers the
# resource providers they need. Create the three subscriptions in the Azure portal first and put their IDs in
# platform.yaml. Client subscriptions are handled by 80-onboard-client.sh.
# Needs: Owner (or Management Group Contributor) at tenant root.
source "$(dirname "$0")/lib.sh"

mg="$(cfg management_group)"
log "Management group $mg"
az account management-group show --name "$mg" -o none 2>/dev/null \
  || az account management-group create --name "$mg" --display-name "BluFire" -o none

for s in platform backup sandbox; do
  sub="$(cfg subscriptions.$s)"
  log "Subscription $s ($sub)"
  add_to_management_group "$sub"
  register_providers "$sub"
done
echo "done. Provider registration finishes in the background; re-run 00 later to confirm sign-in still works."
