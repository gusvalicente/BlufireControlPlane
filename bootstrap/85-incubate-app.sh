#!/usr/bin/env bash
# 85: Prepares an incubating app before its first deploy to the sandbox: its multi-tenant Entra registration and
# the two Key Vault secrets the frontend needs (<app>-auth-secret, <app>-entra-client-secret) in the sandbox vault.
#
#   bootstrap/85-incubate-app.sh <client> <app>
source "$(dirname "$0")/lib.sh"

client="${1:-}" app="${2:-}"
[[ -n "$client" && -n "$app" ]] || die "usage: $0 <client> <app>"
kv="$(name sandbox.keyVault)"
bootstrap/30-entra-app-registrations.sh client-app "$client" "$app"
app_id="$(az ad app list --display-name "blufire-$client-$app" --query '[0].appId' -o tsv)"
bootstrap/lib-app-secrets.sh "$kv" "$app" "$app_id" "$(cfg subscriptions.sandbox)"
echo "Next: register the app repo with bootstrap/40-github-oidc.sh add-app-repo <repo>; its first main build deploys dev."
