#!/usr/bin/env bash
# 70: Deploys sub-blufire-sandbox: one shared Container Apps environment and Postgres server for incubating apps,
# with a db-ops job that is the only one allowed to drop databases. Then updates the backup firewall.
# Needs: 60 done (platformPrincipalId set), Contributor + RBAC Administrator on the sandbox subscription.
source "$(dirname "$0")/lib.sh"

[[ -n "$(setting platformPrincipalId)" ]] || die "run 60-deploy-platform.sh first"
deploy --only sandbox
deploy --only backup
echo "Sandbox ready. Prepare each incubating app with: bootstrap/85-incubate-app.sh <client> <app>"
