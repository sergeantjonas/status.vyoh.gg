#!/usr/bin/env python3
"""Probe each target in targets.toml, write status.json, and POST state
transitions to notify.vyoh.gg. Runs inside .github/workflows/probe.yml.

Previous status comes from the live site (fetched by the workflow before this
script runs), so state transitions survive across runs without the workflow
having to commit anything back to the repo.

If any transition fails to deliver to notify-hub, the script exits non-zero.
GitHub Actions then emails the workflow-failure notification, which doubles as
the box-is-down alert (the hub lives on the same box the prober watches).

Hub contract — POST {NOTIFY_HUB_URL} with Authorization: Bearer <secret>:
	{ "key": "...", "title": "...", "body": "...", "url": "..." }
No `source` field; the hub infers it from the secret. Response is 202 with
{ "duplicate": true/false } on success. See commonplace's notify-hub.md.
"""

from __future__ import annotations

import json
import os
import socket
import ssl
import sys
import time
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

# One entry per probe cycle. 288 ≈ 24h at the current 5-min cadence.
# A single bad probe shows as one red tick, not a whole day going red.
HISTORY_ENTRIES = 288

REPO = Path(__file__).resolve().parent
TARGETS = REPO / "targets.toml"
STATUS = REPO / "status.json"
NOTIFY_HUB_URL = os.environ.get("NOTIFY_HUB_URL", "").rstrip("/")
NOTIFY_HUB_SECRET = os.environ.get("NOTIFY_HUB_SECRET", "")

TIMEOUT = 15
UA = "status.vyoh.gg prober (+https://github.com/sergeantjonas/status.vyoh.gg)"


def probe(host: str, path: str, expected: list[int]) -> tuple[bool, int, str | None]:
	url = f"https://{host}{path}"
	req = urllib.request.Request(url, method="GET", headers={"User-Agent": UA})
	try:
		with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
			code = resp.status
	except urllib.error.HTTPError as e:
		code = e.code
	except (urllib.error.URLError, socket.timeout, TimeoutError, ssl.SSLError, ConnectionError) as e:
		return False, 0, str(e)
	return (code in expected), code, None


def notify(host: str, state: str, code: int, err: str | None, checked_at: int) -> bool:
	"""POST a transition envelope to notify-hub. Return True on 2xx.
	The envelope matches the hub's /messages contract: no `source` field
	(the Bearer secret identifies the source), key has no whitespace."""
	if not NOTIFY_HUB_URL or not NOTIFY_HUB_SECRET:
		print(f"notify-hub not configured; could not deliver {host} {state}", file=sys.stderr)
		return False

	if state == "down":
		detail = f"HTTP {code}" if code else (err or "no response")
		envelope = {
			"key": f"{host}:down:{checked_at}",
			"title": f"{host} is down",
			"body": detail,
			"url": "https://status.vyoh.gg/",
		}
	else:
		envelope = {
			"key": f"{host}:up:{checked_at}",
			"title": f"{host} recovered",
			"body": f"HTTP {code}",
			"url": "https://status.vyoh.gg/",
		}

	req = urllib.request.Request(
		NOTIFY_HUB_URL,
		data=json.dumps(envelope).encode(),
		method="POST",
		headers={
			"Content-Type": "application/json",
			"Authorization": f"Bearer {NOTIFY_HUB_SECRET}",
		},
	)
	try:
		with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
			if 200 <= resp.status < 300:
				return True
			print(f"notify-hub returned {resp.status} for {host} {state}", file=sys.stderr)
			return False
	except urllib.error.HTTPError as e:
		# 401 (bad secret) and 5xx (hub trouble) are retryable; 400 means the
		# envelope is wrong on our side and retrying never helps. Either way,
		# fail the workflow so the owner sees it in the failure email.
		print(f"notify-hub returned HTTP {e.code} for {host} {state}", file=sys.stderr)
		return False
	except Exception as e:
		print(f"notify-hub POST failed for {host} {state}: {e}", file=sys.stderr)
		return False


def load_previous() -> dict[str, dict]:
	if not STATUS.exists():
		return {}
	try:
		data = json.loads(STATUS.read_text())
	except Exception:
		return {}
	return {t["host"]: t for t in data.get("targets", [])}


def update_history(prev_history: list, ts: int, state: str) -> list:
	"""Append this probe's result to the per-probe history, cap at
	HISTORY_ENTRIES, chronologically ordered oldest-first."""
	# Normalise defensively — a prior malformed status.json shouldn't crash.
	history = []
	for entry in prev_history or []:
		if isinstance(entry, list) and len(entry) == 2 and isinstance(entry[0], int):
			history.append([entry[0], entry[1]])

	history.append([ts, state])
	if len(history) > HISTORY_ENTRIES:
		history = history[-HISTORY_ENTRIES:]
	return history


def main() -> None:
	config = tomllib.loads(TARGETS.read_text())
	previous = load_previous()
	now = int(time.time())
	results: list[dict] = []
	transitions: list[tuple[str, str, int, str | None]] = []

	for t in config.get("target", []):
		host = t["host"]
		path = t.get("path", "/")
		expected = t.get("expected", [200, 301, 302])
		group = t.get("group", "other")

		ok, code, err = probe(host, path, expected)
		state = "up" if ok else "down"
		prev = previous.get(host, {})
		history = update_history(prev.get("history", []), now, state)

		results.append({
			"host": host,
			"group": group,
			"path": path,
			"state": state,
			"code": code,
			"error": err,
			"checked_at": now,
			"last_ok": now if ok else prev.get("last_ok", 0),
			"last_fail": now if not ok else prev.get("last_fail", 0),
			"history": history,
		})

		prev_state = prev.get("state")
		if prev_state and prev_state != state:
			transitions.append((host, state, code, err))

	STATUS.write_text(json.dumps({
		"generated_at": now,
		"targets": results,
	}, indent=2) + "\n")

	all_delivered = True
	for host, state, code, err in transitions:
		if not notify(host, state, code, err, now):
			all_delivered = False

	if not all_delivered:
		sys.exit(1)


if __name__ == "__main__":
	main()
