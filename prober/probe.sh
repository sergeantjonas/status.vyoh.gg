#!/usr/bin/env bash
# Probe each public hostname on this VPS over IPv4 and IPv6, then ping its
# healthchecks.io check with success or /fail. Ping URLs are read from the
# PING_* env vars loaded by the systemd service's EnvironmentFile.
#
# Always exits 0: a dead script becomes silence, which the check turns into
# an alert on its own.

set -u

TIMEOUT=10

# host|path|expected|env-var
TARGETS=(
	"vyoh.gg|/|200|PING_vyoh_gg"
	"api.vyoh.gg|/health|200|PING_api_vyoh_gg"
	"engram.vyoh.gg|/|200|PING_engram_vyoh_gg"
	"api.engram.vyoh.gg|/ready|200|PING_api_engram_vyoh_gg"
)

body_file=$(mktemp -t status-probe-body.XXXXXX)
trap 'rm -f "$body_file"' EXIT

# Pipe the ping URL into curl via `-K -` so it never appears in argv.
# Anyone holding the URL can fake a success on this check.
ping() {
	local url=$1
	[[ -z "$url" ]] && return 0
	{
		printf 'silent\nshow-error\nfail\nmax-time 10\n'
		printf 'url "%s"\n' "$url"
		printf 'data-binary @%s\n' "$body_file"
	} | curl -K - >/dev/null 2>&1 || true
}

probe_one() {
	local host=$1 path=$2 expected=$3 family=$4
	local code err
	err=$(mktemp -t status-probe-err.XXXXXX)
	code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time "$TIMEOUT" \
		"-$family" "https://${host}${path}" 2>"$err") || code="000"
	if [[ "$code" == "$expected" ]]; then
		rm -f "$err"
		return 0
	fi
	{
		printf 'IPv%s %s%s -> %s (expected %s)' "$family" "$host" "$path" "$code" "$expected"
		if [[ -s "$err" ]]; then
			printf ': '
			tr -d '\n' < "$err"
		fi
		printf '\n'
	} >> "$body_file"
	rm -f "$err"
	return 1
}

for row in "${TARGETS[@]}"; do
	IFS='|' read -r host path expected envvar <<< "$row"
	url="${!envvar-}"

	: > "$body_file"
	ok=1
	for family in 4 6; do
		probe_one "$host" "$path" "$expected" "$family" || ok=0
	done

	if [[ $ok -eq 1 ]]; then
		printf 'up: %s%s on IPv4 and IPv6\n' "$host" "$path" > "$body_file"
		ping "$url"
	else
		ping "${url%/}/fail"
	fi
done

exit 0
