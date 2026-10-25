#!/usr/bin/env bash
# 50: Deploys sub-blufire-backup (immutable backup storage). Safe to re-run; 60, 70 and 80 re-run it so the
# storage firewall admits each newly created Container Apps subnet.
#
#   bootstrap/50-deploy-backup.sh             deploy or update
#   bootstrap/50-deploy-backup.sh mac-mini    create the Mac Mini's service principal (certificate sign-in) and
#                                             grant it read access to dumps and mirrors
#   bootstrap/50-deploy-backup.sh lock        lock the immutability policies (irreversible; read the prompt)
# Needs: Contributor + Role Based Access Control Administrator on the backup subscription.
source "$(dirname "$0")/lib.sh"

sa="$(name backupStorage)"
rg="$(name backupResourceGroup)"
sub="$(cfg subscriptions.backup)"

case "${1:-}" in
  "")
    deploy --only backup
    cat <<TXT

Backup storage $sa is deployed with unlocked immutability policies:
  pg-dumps 90 days, pg-dumps-prepromotion 365 days, repo-mirrors 90 days.
Once you have confirmed those periods, lock them: bootstrap/50-deploy-backup.sh lock
TXT
    ;;
  mac-mini)
    log "Service principal blufire-mac-mini"
    app_id="$(az ad app list --display-name blufire-mac-mini --query '[0].appId' -o tsv)"
    if [[ -z "$app_id" ]]; then
      out="$(az ad sp create-for-rbac --name blufire-mac-mini --create-cert --years 1 -o json)"
      app_id="$(jq -r .appId <<<"$out")"
      echo "Certificate (private key included) written to: $(jq -r .fileWithCertAndPrivateKey <<<"$out")"
      echo "Copy it to the Mac Mini (see heartbeat/README.md), then delete it from this machine."
    fi
    setting_set macMiniPrincipalId "\"$(sp_object_id "$app_id")\""
    echo "Mac Mini app ID (for az login --service-principal): $app_id"
    deploy --only backup
    ;;
  lock)
    read -r -p "Locking makes the retention periods permanent for these containers. Type LOCK to continue: " answer
    [[ "$answer" == "LOCK" ]] || die "not locked"
    for c in pg-dumps pg-dumps-prepromotion repo-mirrors; do
      etag="$(az storage container immutability-policy show --account-name "$sa" --resource-group "$rg" \
        --subscription "$sub" --container-name "$c" --query etag -o tsv)"
      az storage container immutability-policy lock --account-name "$sa" --resource-group "$rg" \
        --subscription "$sub" --container-name "$c" --if-match "$etag" -o none
      echo "locked $c"
    done
    ;;
  *) die "unknown command: $1" ;;
esac
