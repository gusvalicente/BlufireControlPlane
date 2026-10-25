# Restore a database

Never overwrite the damaged database. Restore into a new one, validate, then switch the app over.

| Situation | Use |
| --- | --- |
| Bad data in the last 35 days | Point-in-time restore of the server in the Azure portal (new server name), then copy the database |
| Undo a release | The pre-promotion dump for that release (`pg-dumps/<app>/prod/pre_promotion/...`) |
| Azure backups unavailable | Latest nightly dump, or the off-cloud copy on the Mac Mini drive |

From a dump:
1. Upload the dump to the `migrations` container (or reference it where it is).
2. Start the db-ops job: `migrate-from-blob --database <new_db> --blob <path>` (via `tools/migrate/run_migration.sh`
   style `az rest` call, or ask Claude to run it).
3. Verify with the app owner.
4. Change the app's `PGDATABASE` through a registry change (`environments.prod.env_vars`, approval required).
5. Keep the old database 7 days, then drop it with approval.
