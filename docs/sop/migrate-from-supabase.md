# Migrate an app from Supabase to Azure

One app at a time. The live production app goes straight to graduated (its client subscription); the three apps
still in refinement move into the sandbox first. The steps are the same; only the target differs (`stage` in the
app's registry file decides it).

## Before you start

- The app's registry file exists and the target stack is deployed (graduated: `bootstrap/80-onboard-client.sh`;
  incubating: `bootstrap/85-incubate-app.sh`).
- The app's code is on the template pattern: FastAPI reads `PGHOST`, `PGDATABASE`, `PGUSER` and signs in with its
  managed identity (`templates/app/backend/app/db.py`); Supabase client calls are replaced by backend calls; Supabase
  RLS rules are re-implemented as FastAPI authorization (the restore deliberately drops RLS policies, because they
  call `auth.uid()`, which does not exist on Azure).
- Postgres extensions the app uses (for example `uuid-ossp`, `pgcrypto`) are allowed on the server's
  `azure.extensions` parameter (set in `infra/modules/postgres.bicep`) and created by an app migration.
- You are on the UniFi static IP (backup storage only accepts it), with `az login` done and `pg_dump` 17 installed
  (`brew install postgresql@17`).
- Announce a short write freeze to the client. Supabase stays read-only until cutover is confirmed.

## Steps

1. **Export.** From the platform repo root:
   `SUPABASE_DB_URL='<session pooler URL, port 5432>' tools/migrate/export_from_supabase.sh <app-id> prod`
   It dumps the app schemas (default `public`), counts rows in every table, builds an `identity_map` seed (old user
   id and email only), and uploads all three to the `migrations` container. Note the prefix it prints.
2. **Restore and verify.** `tools/migrate/run_migration.sh <app-id> prod <prefix>` runs three db-ops jobs inside the
   database's private network: create the database and grant the app identity, restore without Supabase-only
   objects, compare row counts. It stops on the first failure and prints the log command.
3. **Deploy the app** by promoting its images in the admin UI (or `request_promotion` through Claude). The backend
   migrations run and create `identity_map`.
4. **Seed identity links.** `tools/migrate/run_migration.sh <app-id> prod <prefix> --seed-identities`.
   Each user is linked to their Entra account the first time they sign in with their company Microsoft login
   (matched on email, only from the client's allowed tenant).
5. **Smoke test** sign-in, a read and a write with the client contact. Check the app's App Insights for errors.
6. **Cut over.** Point the client's bookmarks or DNS to the new URL. Keep Supabase paused (not deleted) for 30 days.
7. **Record it.** The first nightly backup and a manual restore test (`Backups` screen, Test restore) must pass
   before you delete the Supabase project.

## Files and storage

Supabase Storage files are not covered by these scripts. If an app uses Storage, copy the bucket to the app's Blob
container with `azcopy` and update the code to use Blob SAS links issued by the backend.
