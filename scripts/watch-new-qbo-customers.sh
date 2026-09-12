#!/bin/bash
# Watch FOR-138 / FOR-971 for customers created by the hourly Make scenario
# "Add new QBO Client from new PC V3 Client", and tell the n8n session when one
# lands so it can check whether module 12 wrote ExternalClientId back.
#
# Context: bautrey/fpqbo thread with the n8n session, 2026-09-09. The write-back
# has been failing since somewhere in 2026-07-15..2026-08-05 (root cause is in
# Kampilan's Make custom app, not in QBO and not in Partner Connect). n8n's comma
# fix is unexercised because the scenario only reaches module 12 when a genuinely
# new client appears. This watcher is the trigger for that check.
#
# Read-only against QBO. Its only write is a cc-bus message.
# Retire it once the fix is confirmed: crontab -e and drop the line.

set -uo pipefail

STATE_DIR="/Users/burkestudio/projects/fpqbo/docs/scratch"
BUS="http://127.0.0.1:8890"
API="https://qbo-oauth.onrender.com"
mkdir -p "$STATE_DIR"
FAILED=0

notify() {
  # $1 subject, $2 body. Never let a bus failure kill the run.
  python3 - "$1" "$2" <<'PY' || echo "warn: cc-bus send failed" >&2
import json, sys, urllib.request
subject, body = sys.argv[1], sys.argv[2]
# from/type are REQUIRED by MessageCreate. Sending only subject+body returns
# HTTP 422 and the notification is lost — which is how this shipped on
# 2026-09-09 and stayed broken until an ablation drill exposed it.
payload = json.dumps({
    "from": "fpqbo", "type": "notify", "subject": subject, "body": body,
}).encode()
req = urllib.request.Request(
    "http://127.0.0.1:8890/queues/n8n/send",
    data=payload, headers={"Content-Type": "application/json"}, method="POST")
with urllib.request.urlopen(req, timeout=10) as r:
    r.read()
PY
}

check_company() {
  local code="$1" keychain="$2" company_id="$3"
  local key seen_file body new

  key=$(security find-generic-password -a burkestudio -s "$keychain" -w 2>/dev/null) || {
    # Loud on purpose. This returned 0 with a warning until 2026-09-12, so the
    # watcher sat dead under cron for three days and the log read as "nothing
    # new". A watcher that cannot see is not a watcher that saw nothing.
    echo "ERROR: cannot read keychain item $keychain — watcher is BLIND for $code" >&2
    notify "fpqbo watcher is BLIND — cannot read the ${code} API key" \
"The new-customer watcher could not read keychain item \`${keychain}\`, so it is
not watching ${code} and has not been since this started.

Do not read its silence as \"no new customers\". Ask me to check by hand until
this clears.

Known cause: a background security session cannot reach the login keychain
(cron gets \"Background\", where the default keychain is System.keychain and the
login keychain is not in the search list). It runs as a LaunchAgent in the Aqua
session for that reason. If you are seeing this, the agent is running somewhere
it should not be."
    FAILED=1
    return 0; }

  seen_file="$STATE_DIR/.watch-seen-${code}.txt"
  body=$(curl -sS --max-time 60 -H "X-API-Key: $key" \
    "$API/api/customers/?company_id=${company_id}&active_only=false&max_results=1000") || {
    echo "ERROR: $code customer fetch failed" >&2; FAILED=1; return 0; }

  # A truncated page would make absent ids look new. 1000 is QBO's ceiling.
  local count
  count=$(printf '%s' "$body" | jq 'length' 2>/dev/null) || { echo "ERROR: $code returned unparseable json" >&2; FAILED=1; return 0; }
  [ "$count" -ge 1000 ] && { echo "ERROR: $code at the 1000-row ceiling, cannot diff safely" >&2; FAILED=1; return 0; }

  # First run seeds the baseline and reports nothing.
  if [ ! -f "$seen_file" ]; then
    printf '%s' "$body" | jq -r '.[].Id' | sort > "$seen_file"
    echo "$code: seeded $count customers"
    return 0
  fi

  new=$(printf '%s' "$body" \
    | jq -r --slurpfile _ /dev/null '.[] | [.Id, .DisplayName, .MetaData.CreateTime] | @tsv' \
    | sort -t$'\t' -k1,1 \
    | join -t$'\t' -v1 -1 1 -2 1 - "$seen_file" 2>/dev/null)

  printf '%s' "$body" | jq -r '.[].Id' | sort > "$seen_file"

  [ -z "$new" ] && { echo "$code: no new customers"; return 0; }

  echo "$code: NEW -> $new"
  notify "New QBO customer in ${code} — check whether module 12 wrote ExternalClientId" \
"A customer just appeared in ${code} (company_id=${company_id}).

\`\`\`
${new}
\`\`\`

If the CreateTime seconds land in minute :00 this is the hourly scenario, which
means module 12 ran with your comma fix in place. Check the PC client's
\`ExternalClientId\` now — populated within a second or two confirms the fix,
blank means the Make app is still double-encoding and it is Kampilan's app.

Automated from the fpqbo watcher; QBO reads only."
}

check_company FOR-138 fpqbo-api-key-us 1
check_company FOR-971 fpqbo-api-key-ca 2

if [ "$FAILED" -ne 0 ]; then
  echo "run FAILED at $(date -u +%FT%TZ)"
  exit 1
fi
# Heartbeat. Its mtime is the last run that actually saw both companies, so
# "is the watcher alive" is answerable without reading the log.
date -u +%FT%TZ > "$STATE_DIR/.watch-last-success"
exit 0
