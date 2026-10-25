# Shared helpers for bootstrap scripts. Source it; do not run it.
# Scripts run from the repo root: bootstrap/NN-name.sh

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

log() { printf '\n==> %s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

require_cmd() {
  for c in "$@"; do command -v "$c" >/dev/null 2>&1 || die "missing command: $c"; done
}

# cfg subscriptions.platform  -> value from platform.yaml (dotted path)
cfg() {
  python3 - "$1" <<'PY'
import sys, yaml
value = yaml.safe_load(open("platform.yaml"))
for part in sys.argv[1].split("."):
    value = value[part]
print(value if not isinstance(value, (list, dict)) else __import__("json").dumps(value))
PY
}

# setting apiAudience  -> value from infra/platform-settings.json
setting() {
  python3 -c 'import json,sys; v=json.load(open("infra/platform-settings.json")).get(sys.argv[1], ""); print(v if isinstance(v, str) else json.dumps(v))' "$1"
}

# setting_set key '"json value"'  (value is JSON: strings need quotes)
setting_set() {
  python3 - "$1" "$2" <<'PY'
import json, sys
path = "infra/platform-settings.json"
data = json.load(open(path))
data[sys.argv[1]] = json.loads(sys.argv[2])
open(path, "w").write(json.dumps(data, indent=2) + "\n")
PY
}

# name acr  -> platform resource name from tools/render_params.py --names
name() {
  python3 tools/render_params.py --names | python3 -c 'import json,sys; d=json.load(sys.stdin); v=d
for p in sys.argv[1].split("."): v=v[p]
print(v)' "$1"
}

register_providers() {
  local sub="$1"
  for ns in Microsoft.App Microsoft.ContainerRegistry Microsoft.DBforPostgreSQL Microsoft.KeyVault \
            Microsoft.ManagedIdentity Microsoft.Network Microsoft.OperationalInsights Microsoft.Insights \
            Microsoft.OperationsManagement Microsoft.SecurityInsights Microsoft.Storage \
            Microsoft.AlertsManagement Microsoft.Communication; do
    az provider register --namespace "$ns" --subscription "$sub" --only-show-errors >/dev/null
  done
}

add_to_management_group() {
  local sub="$1"
  az account management-group subscription add --name "$(cfg management_group)" --subscription "$sub" --only-show-errors >/dev/null
}

signed_in_object_id() { az ad signed-in-user show --query id -o tsv; }

sp_object_id() { az ad sp show --id "$1" --query id -o tsv; }

# Fails if any value in platform.yaml still contains REPLACE for the given keys.
require_set() {
  for key in "$@"; do
    v="$(cfg "$key")"
    [[ "$v" == *REPLACE* || "$v" == 00000000-0000-0000-0000-00000000000* ]] && die "platform.yaml: $key is not set ($v)"
  done
  return 0
}

deploy() { python3 infra/scripts/deploy.py apply "$@"; }
