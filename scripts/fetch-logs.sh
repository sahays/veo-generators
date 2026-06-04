#!/usr/bin/env bash
#
# fetch-logs.sh — Fetch Cloud Logging entries via the VM's attached service
# account (metadata server), bypassing expired `gcloud auth` user credentials.
#
# Works anywhere the GCE/Cloud-Run metadata server is reachable and the attached
# service account has roles/logging.viewer.
#
# Usage:
#   scripts/fetch-logs.sh [options]
#
# Options:
#   -f, --filter FILTER     Extra Cloud Logging filter, ANDed with the base.
#                           e.g. 'textPayload:"thumbnail"'
#   -s, --service NAME      Cloud Run service name (resource.labels.service_name).
#   -S, --severity LEVEL    Minimum severity (default: DEFAULT). e.g. ERROR, WARNING.
#   -F, --freshness DUR     Look back this far (default: 1h). e.g. 30m, 2h, 1d.
#   -n, --limit N           Max entries to return (default: 50).
#   -p, --project ID        GCP project (default: gcloud config, else metadata).
#       --raw               Print raw JSON entries instead of formatted lines.
#       --order ORDER       "desc" (newest first, default) or "asc".
#
# Examples:
#   scripts/fetch-logs.sh -s veo-generators-worker -S ERROR -F 6h
#   scripts/fetch-logs.sh -f 'textPayload:"thumbnail"' -F 24h -n 100
#   scripts/fetch-logs.sh -f 'jsonPayload.record_id="abc123"' --raw
#
set -euo pipefail

# ── Defaults ────────────────────────────────────────────────────────────────
FILTER=""
SERVICE=""
SEVERITY="DEFAULT"
FRESHNESS="1h"
LIMIT=50
PROJECT=""
RAW=0
ORDER="desc"

# ── Parse args ──────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    -f|--filter)    FILTER="$2"; shift 2 ;;
    -s|--service)   SERVICE="$2"; shift 2 ;;
    -S|--severity)  SEVERITY="$2"; shift 2 ;;
    -F|--freshness) FRESHNESS="$2"; shift 2 ;;
    -n|--limit)     LIMIT="$2"; shift 2 ;;
    -p|--project)   PROJECT="$2"; shift 2 ;;
    --raw)          RAW=1; shift ;;
    --order)        ORDER="$2"; shift 2 ;;
    -h|--help)      sed -n '2,40p' "$0"; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

# ── Resolve project ─────────────────────────────────────────────────────────
META="http://metadata.google.internal/computeMetadata/v1"
MH=(-H "Metadata-Flavor: Google")
if [[ -z "$PROJECT" ]]; then
  PROJECT="$(gcloud config get-value project 2>/dev/null || true)"
fi
if [[ -z "$PROJECT" || "$PROJECT" == "(unset)" ]]; then
  PROJECT="$(curl -s "${MH[@]}" "$META/project/project-id")"
fi

# ── Get access token from metadata server ───────────────────────────────────
TOKEN="$(curl -s "${MH[@]}" "$META/instance/service-accounts/default/token" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")"
if [[ -z "$TOKEN" ]]; then
  echo "ERROR: could not obtain access token from metadata server" >&2
  exit 1
fi

# ── Convert freshness (30m/2h/1d) into a timestamp filter ───────────────────
START_TS="$(python3 - "$FRESHNESS" <<'PY'
import sys, re, datetime
dur = sys.argv[1]
m = re.fullmatch(r"(\d+)([smhd])", dur.strip())
if not m:
    sys.stderr.write("Invalid freshness: %s (use e.g. 30m, 2h, 1d)\n" % dur)
    sys.exit(1)
n, unit = int(m.group(1)), m.group(2)
secs = n * {"s":1, "m":60, "h":3600, "d":86400}[unit]
ts = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=secs)
print(ts.strftime("%Y-%m-%dT%H:%M:%SZ"))
PY
)"

# ── Build the combined filter ───────────────────────────────────────────────
FULL_FILTER="timestamp>=\"$START_TS\" severity>=$SEVERITY"
if [[ -n "$SERVICE" ]]; then
  FULL_FILTER="$FULL_FILTER resource.labels.service_name=\"$SERVICE\""
fi
if [[ -n "$FILTER" ]]; then
  FULL_FILTER="$FULL_FILTER $FILTER"
fi

# ── Query the Logging API ───────────────────────────────────────────────────
BODY="$(FL_PROJECT="$PROJECT" FL_FILTER="$FULL_FILTER" FL_ORDER="$ORDER" FL_LIMIT="$LIMIT" \
python3 - <<'PY'
import json, os
print(json.dumps({
  "resourceNames": ["projects/" + os.environ["FL_PROJECT"]],
  "filter": os.environ["FL_FILTER"],
  "orderBy": "timestamp " + os.environ["FL_ORDER"],
  "pageSize": int(os.environ["FL_LIMIT"]),
}))
PY
)"

RESP=""
for attempt in 1 2 3; do
  RESP="$(curl -s --max-time 30 -X POST "https://logging.googleapis.com/v2/entries:list" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d "$BODY" || true)"
  [[ -n "$RESP" ]] && break
  echo "# empty response (attempt $attempt), retrying..." >&2
  sleep 1
done

# ── Output ──────────────────────────────────────────────────────────────────
echo "# project=$PROJECT  since=$START_TS  severity>=$SEVERITY  service=${SERVICE:-*}" >&2
echo "# filter: $FULL_FILTER" >&2

if [[ "$RAW" == "1" ]]; then
  echo "$RESP" | python3 -m json.tool
  exit 0
fi

FL_RESP="$RESP" python3 - <<'PY'
import os, json
raw = os.environ.get("FL_RESP", "").strip()
if not raw:
    print("(empty response from Logging API — check token/permissions or retry)")
    sys.exit(0)
try:
    data = json.loads(raw)
except json.JSONDecodeError:
    print("Non-JSON response:")
    print(raw[:2000])
    sys.exit(1)
if "error" in data:
    print("API ERROR:", json.dumps(data["error"], indent=2))
    sys.exit(1)
entries = data.get("entries", [])
if not entries:
    print("(no matching log entries)")
for e in entries:
    ts = e.get("timestamp", "")
    sev = e.get("severity", "DEFAULT")
    svc = e.get("resource", {}).get("labels", {}).get("service_name", "?")
    if "textPayload" in e:
        msg = e["textPayload"]
    elif "jsonPayload" in e:
        jp = e["jsonPayload"]
        msg = jp.get("message") or json.dumps(jp)
    elif "httpRequest" in e:
        h = e["httpRequest"]
        msg = (f"{h.get('requestMethod','')} {h.get('status','')} "
               f"{h.get('requestUrl','')} ({h.get('latency','')})")
    else:
        msg = json.dumps(e.get("protoPayload", {}))
    print(f"{ts}  {sev:<8} {svc:<24} {msg}")
print(f"\n# {len(entries)} entries", file=sys.stderr)
PY
