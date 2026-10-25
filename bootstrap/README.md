# Bootstrap

One-time setup of the BluFire Azure estate, run from the repo root on Gus's machine (on the UniFi static IP, signed
in with `az login --tenant <tenant-id>` as the cloud-only admin account). After bootstrap, every change flows through
git: the admin UI or a PR edits the registry, and `.github/workflows/apply.yml` deploys it.

Tools: `az` (with Bicep), `python3` with `pyyaml` and `jsonschema`, `jq`, `git`, `openssl`. `gh` is optional.

| Step | Script | What it does | Run again when |
| --- | --- | --- | --- |
| 0 | `00-prereqs-check.sh` | Checks tools, tenant, platform.yaml values, that the registry renders | Any time |
| 1 | `10-management-group-and-subscriptions.sh` | Creates `mg-blufire`, moves the platform, backup and sandbox subscriptions under it, registers providers | Never |
| 2 | `20-policy-and-defender.sh` | Policy baseline (allowed region, tag reporting, Postgres public access denied), custom `BluFire What-If` role, Defender status and security contact | Policy changes |
| 3 | `30-entra-app-registrations.sh` | platform-api (roles Admin/Agent), admin UI, MCP (prints the Claude connector secret once) | `rotate-mcp-secret` yearly |
| 4 | `40-github-oidc.sh` | OIDC identities for apply, what-if and app builds | Per app repo: `add-app-repo <repo>` |
| 5 | `50-deploy-backup.sh` | Immutable backup storage | `mac-mini` once, `lock` once |
| 6 | `60-deploy-platform.sh --github-app-key key.pem` | Control plane in four passes, Key Vault secrets, image builds, custom domains, platform identity roles | Re-run passes with `--skip-build` / `--domains-only` |
| 7 | `70-deploy-sandbox.sh` | Shared sandbox environment and Postgres | Never (apply.yml keeps it current) |
| 8 | `85-incubate-app.sh <client> <app>` | Entra registration and Key Vault secrets for a new incubating app | Per app |
| 9 | `80-onboard-client.sh <client>` | Moves `sub-<client>` under the management group and deploys its shared stack | Per client |
| 10 | `90-graduate-app.sh <client> <app>` | After the graduation PR merges: client stack, secrets, app envs, database grants, sandbox cleanup | Per graduation |

Re-run `40-github-oidc.sh` after step 5 so the deploy identity gets write access to `scan-results` and `repo-mirrors`.
Commit `infra/platform-settings.json` and `infra/platform-images.json` whenever a script changes them.

## Manual steps no script can do

- Create the three platform subscriptions (and each `sub-<client>`) in the Azure portal.
- Verify the custom domain in Entra (needed for the MCP Application ID URI) and create the DNS records `60` prints.
- Create the Entra group `pg-admins` with yourself in it and put its object ID in `platform.yaml`.
- Create a GitHub App for the platform repo (contents and pull requests: write) and download its private key.
  Allow it to bypass branch protection on `main` for low-risk commits.
- Connect GitHub to Defender for Cloud (Environment settings > Add environment > GitHub) for DevOps posture.
- Lock the backup immutability policies once retention is confirmed: `50-deploy-backup.sh lock`. Locking is permanent.

## Conventions

- Key Vault secret names in app vaults equal the registry `secrets` names. Name them `<app>-<purpose>`
  (for example `intake-portal-smtp-password`); containers read them as upper-case env vars with hyphens as
  underscores (`INTAKE_PORTAL_SMTP_PASSWORD`). Every app also gets `<app>-auth-secret` and
  `<app>-entra-client-secret` (created by `85` and `90`).
- Backup containers: `pg-dumps` (nightly and manual, 90 days), `pg-dumps-prepromotion` (365 days), `repo-mirrors`
  (90 days), `dbops-results`, `migrations` (deleted after 30 days), `scan-results`.
- Origin restriction blocks Azure availability tests unless their published IP ranges are added to
  `availabilityTestCidrs` in `infra/platform-settings.json`. Render warns when a prod app has origins on without them.
