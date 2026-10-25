#!/usr/bin/env bash
# Nightly off-cloud copy (layer 4): pull new prod dumps and repo mirrors from backup storage to the external drive,
# verify each dump's SHA-256 against its manifest, prune to 30 daily + 12 monthly, then upload a receipt.
# Runs from launchd at 03:30 local on the M2 Mac Mini, signed in as the read-only mac-mini service principal.
set -euo pipefail

ACCOUNT="${BACKUP_STORAGE_ACCOUNT:?}"
DEST="${BLUFIRE_BACKUP_DIR:-/Volumes/BluFireBackup/blufire}"
[[ -d "$(dirname "$DEST")" ]] || { echo "backup drive not mounted"; exit 1; }
mkdir -p "$DEST"

az login --service-principal -u "$MAC_SP_APP_ID" --tenant "$TENANT_ID" --certificate "$HOME/.blufire/mac-mini-sp.pem" \
  --only-show-errors >/dev/null

ok=true; detail=""; size=0
for container in pg-dumps repo-mirrors; do
  az storage blob download-batch --auth-mode login --account-name "$ACCOUNT" --source "$container" \
    --destination "$DEST/$container" --overwrite false --only-show-errors >/dev/null || { ok=false; detail+="download $container failed; "; }
done

while IFS= read -r -d '' dump; do
  manifest="$dump.manifest.json"
  [[ -f "$manifest" ]] || continue
  want="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["sha256"])' "$manifest")"
  have="$(shasum -a 256 "$dump" | cut -d' ' -f1)"
  [[ "$want" == "$have" ]] || { ok=false; detail+="checksum mismatch ${dump#$DEST/}; "; }
  size=$((size + $(stat -f%z "$dump")))
done < <(find "$DEST/pg-dumps" -name '*.dump' -mtime -2 -print0)

# Keep the newest 30 nightly dumps per app/env, plus the first dump of each of the last 12 months.
python3 - "$DEST/pg-dumps" <<'PY'
import sys
from pathlib import Path
root = Path(sys.argv[1])
for folder in {p.parent for p in root.rglob("*.dump") if p.parent.name == "nightly"}:
    dumps = sorted(folder.glob("*.dump"))
    keep = set(dumps[-30:])
    monthly = {}
    for d in dumps:
        monthly.setdefault(d.name[:6], d)
    keep |= set(sorted(monthly.values())[-12:])
    for d in dumps:
        if d not in keep:
            d.unlink()
            Path(f"{d}.manifest.json").unlink(missing_ok=True)
PY

receipt="$(mktemp)"
python3 - "$receipt" "$ok" "$detail" "$size" "$DEST" <<'PY'
import json, sys, datetime
path, ok, detail, size, dest = sys.argv[1:]
json.dump({"kind": "off_cloud", "app": "all", "env": "prod", "ok": ok == "true", "detail": detail,
           "size_bytes": int(size), "location": f"M2 Mac Mini {dest}",
           "finished_at": datetime.datetime.now(datetime.UTC).isoformat()}, open(path, "w"))
PY
az storage blob upload --auth-mode login --account-name "$ACCOUNT" --container-name dbops-results \
  --name "all/prod/off_cloud/$(date -u +%Y%m%dT%H%M%SZ).json" --file "$receipt" --only-show-errors >/dev/null
rm -f "$receipt"
$ok
