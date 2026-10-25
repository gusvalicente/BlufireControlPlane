#!/usr/bin/env bash
# 40: GitHub Actions sign-in to Azure with OIDC (no stored Azure secrets).
#
#   bootstrap/40-github-oidc.sh                       deploy + what-if identities for the platform repo
#   bootstrap/40-github-oidc.sh add-app-repo <repo>   let an app repo's main branch push images to the registry
#
# gh-blufire-deploy   main branch of the platform repo (apply, image builds, nightly scans and mirrors).
#                     Contributor + Role Based Access Control Administrator on mg-blufire, Storage Blob Data
#                     Contributor on the scan-results and repo-mirrors containers (after 50 has run).
# gh-blufire-whatif   pull requests on the platform repo. Custom "BluFire What-If" role (from 20) + Reader.
# gh-blufire-builds   main branch of each app repo. AcrPush on the platform registry only (after 60 has run).
# Needs: Application Administrator in Entra and Owner on mg-blufire.
source "$(dirname "$0")/lib.sh"
require_cmd az python3

org="$(cfg github.org)"
repo="$(cfg github.platform_repo)"
mg_scope="/providers/Microsoft.Management/managementGroups/$(cfg management_group)"
issuer="https://token.actions.githubusercontent.com"

ensure_app() {
  local id
  id="$(az ad app list --display-name "$1" --query '[0].appId' -o tsv)"
  [[ -n "$id" ]] || id="$(az ad app create --display-name "$1" --sign-in-audience AzureADMyOrg --query appId -o tsv)"
  az ad sp show --id "$id" -o none 2>/dev/null || az ad sp create --id "$id" -o none
  echo "$id"
}

ensure_federation() { # app-id credential-name subject
  if [[ -z "$(az ad app federated-credential list --id "$1" --query "[?name=='$2'].name | [0]" -o tsv)" ]]; then
    az ad app federated-credential create --id "$1" --parameters "{
      \"name\": \"$2\", \"issuer\": \"$issuer\", \"subject\": \"$3\", \"audiences\": [\"api://AzureADTokenExchange\"]
    }" -o none
  fi
}

ensure_role() { # assignee-app-id role scope
  az role assignment create --assignee "$1" --role "$2" --scope "$3" -o none --only-show-errors
}

platform_repo() {
  log "gh-blufire-deploy ($org/$repo main)"
  deploy_id="$(ensure_app gh-blufire-deploy)"
  ensure_federation "$deploy_id" platform-main "repo:$org/$repo:ref:refs/heads/main"
  ensure_role "$deploy_id" "Contributor" "$mg_scope"
  ensure_role "$deploy_id" "Role Based Access Control Administrator" "$mg_scope"

  backup_sa="$(name backupStorage)"
  backup_rg="$(name backupResourceGroup)"
  sa_scope="/subscriptions/$(cfg subscriptions.backup)/resourceGroups/$backup_rg/providers/Microsoft.Storage/storageAccounts/$backup_sa"
  if az storage account show --ids "$sa_scope" -o none 2>/dev/null; then
    for c in scan-results repo-mirrors; do
      ensure_role "$deploy_id" "Storage Blob Data Contributor" "$sa_scope/blobServices/default/containers/$c"
    done
  else
    echo "note: backup storage not deployed yet; re-run this script after 50"
  fi

  log "gh-blufire-whatif ($org/$repo pull requests)"
  whatif_id="$(ensure_app gh-blufire-whatif)"
  ensure_federation "$whatif_id" platform-pr "repo:$org/$repo:pull_request"
  ensure_role "$whatif_id" "Reader" "$mg_scope"
  ensure_role "$whatif_id" "BluFire What-If" "$mg_scope"

  deploy_sp="$(sp_object_id "$deploy_id")"
  # AzureActivity.Caller can carry either the object ID or the app ID of a service principal; list both.
  setting_set ciPrincipalIds "[\"$deploy_sp\", \"$deploy_id\"]"

  cat <<TXT

Set these in GitHub ($org/$repo > Settings > Secrets and variables > Actions > Variables):
  AZURE_TENANT_ID          $(cfg tenant_id)
  AZURE_SUBSCRIPTION_ID    $(cfg subscriptions.platform)
  AZURE_DEPLOY_CLIENT_ID   $deploy_id
  AZURE_WHATIF_CLIENT_ID   $whatif_id
And as secrets (from the GitHub App you created for the platform):
  PLATFORM_APP_ID, PLATFORM_APP_PRIVATE_KEY
infra/platform-settings.json now lists the deploy identity in ciPrincipalIds (Sentinel ignores its changes). Commit it.
TXT
  command -v gh >/dev/null && gh auth status >/dev/null 2>&1 && {
    gh variable set AZURE_TENANT_ID --repo "$org/$repo" --body "$(cfg tenant_id)"
    gh variable set AZURE_SUBSCRIPTION_ID --repo "$org/$repo" --body "$(cfg subscriptions.platform)"
    gh variable set AZURE_DEPLOY_CLIENT_ID --repo "$org/$repo" --body "$deploy_id"
    gh variable set AZURE_WHATIF_CLIENT_ID --repo "$org/$repo" --body "$whatif_id"
    echo "GitHub variables set with gh."
  } || true
}

add_app_repo() {
  local app_repo="$1"
  [[ -n "$app_repo" ]] || die "usage: $0 add-app-repo <repo-name>"
  log "gh-blufire-builds for $org/$app_repo"
  builds_id="$(ensure_app gh-blufire-builds)"
  ensure_federation "$builds_id" "$app_repo-main" "repo:$org/$app_repo:ref:refs/heads/main"
  acr_scope="/subscriptions/$(cfg subscriptions.platform)/resourceGroups/$(name resourceGroup)/providers/Microsoft.ContainerRegistry/registries/$(name acr)"
  ensure_role "$builds_id" "AcrPush" "$acr_scope"
  cat <<TXT

In $org/$app_repo set variables AZURE_TENANT_ID, AZURE_SUBSCRIPTION_ID (platform), AZURE_BUILDS_CLIENT_ID=$builds_id,
ACR_NAME=$(name acr), and secrets PLATFORM_APP_ID, PLATFORM_APP_PRIVATE_KEY (GitHub App with contents:write on $repo).
TXT
}

case "${1:-}" in
  "") platform_repo ;;
  add-app-repo) add_app_repo "${2:-}" ;;
  *) die "unknown command: $1" ;;
esac
