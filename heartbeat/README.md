# M2 Mac Mini: off-cloud heartbeat and backup copy

The Mini is the one piece of the platform outside Azure. It does two jobs:

| Job | File | Schedule | Alerts through |
| --- | --- | --- | --- |
| Heartbeat: every prod app's `/api/health`, plus the control plane worker freshness | `heartbeat.py` | every 5 minutes | iMessage from the Mini (and an optional webhook) |
| Off-cloud backup copy (layer 4): prod dumps and repo mirrors to the external drive, checksums verified | `offcloud_backup.sh` | 03:30 local | Receipt in `dbops-results`, shown in the admin UI and digest |

It runs from the UniFi static IP, so it passes every origin restriction.

## Setup (once)

1. On the MacBook (platform repo root): `bootstrap/50-deploy-backup.sh mac-mini`. It creates the `blufire-mac-mini`
   service principal with a certificate and grants it read access to dumps and mirrors and write access to
   `dbops-results` only. Copy the printed PEM file to the Mini as `~/.blufire/mac-mini-sp.pem` (`chmod 600`), then
   delete it from the MacBook.
2. On the Mini: `brew install azure-cli`, sign Messages in with an Apple ID that can text your phone, and plug in the
   backup drive (name it `BluFireBackup`, APFS encrypted).
3. Clone this repo to `~/blufire` (read-only use; the Mini never commits).
4. Store the heartbeat token (from Key Vault secret `heartbeat-token`):
   `security add-generic-password -s blufire-heartbeat -a blufire -w '<token>'`
5. Create `~/.blufire/heartbeat.json` (example in the header of `heartbeat.py`): the admin UI heartbeat URL
   `https://<domains.admin_ui>/api/heartbeat`, one target per prod app, your phone number.
6. Edit the two plists (replace `REPLACE`), copy them to `~/Library/LaunchAgents/`, then
   `launchctl load ~/Library/LaunchAgents/com.blufire.heartbeat.plist` and the same for the backup plist.
7. Test: `python3 ~/blufire/heartbeat/heartbeat.py` prints one line of results; stop a dev app or point a target at
   a bad URL to see the iMessage arrive.

The service principal certificate expires after one year. Renew it with `50-deploy-backup.sh mac-mini` after deleting
the old app registration, or `az ad app credential reset --id <app-id> --create-cert`.
