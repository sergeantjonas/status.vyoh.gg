#!/usr/bin/env python3
"""Probe each target in targets.toml, write status.json, and POST state
transitions to notify.vyoh.gg. Runs inside .github/workflows/probe.yml.

Previous status comes from the live site (fetched by the workflow before this
script runs), so state transitions survive across runs without the workflow
having to commit anything back to the repo.

A host counts as down for a cycle only if every in-run attempt fails, and a
down alert fires only after CONFIRM_CYCLES such cycles in a row. Runner network
blips and momentary proxy 502s usually clear before the next run and don't page.
A recovery alert fires only for a host whose down alert fired.

If any alert fails to deliver to notify-hub, the script exits non-zero.
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
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# One entry per probe cycle, kept for the page's 24h strip. Pruned by age
# rather than count because the cadence depends on which trigger fires.
# A single bad probe shows as one red tick, not a whole day going red.
HISTORY_WINDOW = 24 * 3600

REPO = Path(__file__).resolve().parent
TARGETS = REPO / "targets.toml"
STATUS = REPO / "status.json"
NOTIFY_HUB_URL = os.environ.get("NOTIFY_HUB_URL", "").rstrip("/")
NOTIFY_HUB_SECRET = os.environ.get("NOTIFY_HUB_SECRET", "")

TIMEOUT = 15
RETRIES = 2
RETRY_DELAY = 5
# At the 15-min Worker cadence, a real outage alerts 15–30 min after it starts.
CONFIRM_CYCLES = 2
UA = "status.vyoh.gg prober (+https://github.com/sergeantjonas/status.vyoh.gg)"


def describe(code: int, err: str | None) -> str:
	return f"HTTP {code}" if code else (err or "no response")


def probe_once(host: str, path: str, expected: list[int]) -> tuple[bool, int, str | None]:
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


def probe(host: str, path: str, expected: list[int]) -> tuple[bool, int, str | None, list[str]]:
	"""Probe with up to RETRIES retries. Also returns each failed attempt's
	outcome, so the Actions log shows what a retry absorbed."""
	failures: list[str] = []
	for attempt in range(1 + RETRIES):
		if attempt:
			time.sleep(RETRY_DELAY)
		ok, code, err = probe_once(host, path, expected)
		if ok:
			break
		failures.append(describe(code, err))
	return ok, code, err, failures


def notify(host: str, state: str, code: int, err: str | None, checked_at: int) -> bool:
	"""POST a transition envelope to notify-hub. Return True on 2xx.
	The envelope matches the hub's /messages contract: no `source` field
	(the Bearer secret identifies the source), key has no whitespace."""
	if not NOTIFY_HUB_URL or not NOTIFY_HUB_SECRET:
		print(f"notify-hub not configured; could not deliver {host} {state}", file=sys.stderr)
		return False

	if state == "down":
		envelope = {
			"key": f"{host}:down:{checked_at}",
			"title": f"{host} is down",
			"body": describe(code, err),
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
	# The key is fixed across attempts, so the hub dedupes a retry whose
	# predecessor landed but lost its response.
	for attempt in range(1 + RETRIES):
		if attempt:
			time.sleep(RETRY_DELAY)
		try:
			with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
				if 200 <= resp.status < 300:
					return True
				print(f"notify-hub returned {resp.status} for {host} {state}", file=sys.stderr)
				return False
		except urllib.error.HTTPError as e:
			# 5xx is hub trouble and worth another attempt. 4xx (bad envelope,
			# bad secret) repeats identically. Either way a False fails the
			# workflow so the owner sees it in the failure email.
			print(f"notify-hub returned HTTP {e.code} for {host} {state}", file=sys.stderr)
			if e.code < 500:
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
	"""Append this probe's result to the per-probe history, drop entries
	older than HISTORY_WINDOW, chronologically ordered oldest-first."""
	# Normalise defensively — a prior malformed status.json shouldn't crash.
	history = []
	for entry in prev_history or []:
		if isinstance(entry, list) and len(entry) == 2 and isinstance(entry[0], int):
			history.append([entry[0], entry[1]])

	history.append([ts, state])
	cutoff = ts - HISTORY_WINDOW
	return [entry for entry in history if entry[0] > cutoff]


def main() -> None:
	config = tomllib.loads(TARGETS.read_text())
	previous = load_previous()
	now = int(time.time())
	results: list[dict] = []
	transitions: list[tuple[str, str, int, str | None]] = []

	targets = [
		(t["host"], t.get("path", "/"), t.get("expected", [200, 301, 302]), t.get("group", "other"))
		for t in config.get("target", [])
	]
	# Concurrent so retries against a dead box cost one host's worth of
	# timeouts rather than one per host.
	with ThreadPoolExecutor(max_workers=len(targets) or 1) as pool:
		outcomes = list(pool.map(lambda t: probe(*t[:3]), targets))

	for (host, path, expected, group), (ok, code, err, failures) in zip(targets, outcomes):
		state = "up" if ok else "down"
		prev = previous.get(host, {})
		history = update_history(prev.get("history", []), now, state)

		# Missing gate fields: treat a stored down as already alerted, so its
		# recovery still notifies and the outage isn't alerted twice.
		was_down = prev.get("state") == "down"
		fail_streak = 0 if ok else prev.get("fail_streak", int(was_down)) + 1
		# Set on attempt, not delivery: an undelivered alert fails the
		# workflow, and the failure email stands in for it.
		alerted = prev.get("alerted", was_down)
		if not ok and not alerted and fail_streak >= CONFIRM_CYCLES:
			transitions.append((host, "down", code, err))
			alerted = True
		elif ok and alerted:
			transitions.append((host, "up", code, err))
			alerted = False

		line = f"{host:24} {state:4} {describe(code, err)}"
		if ok and failures:
			line += f"  after {len(failures)} failed: {'; '.join(failures)}"
		if not ok:
			line += f"  streak {fail_streak}/{CONFIRM_CYCLES}"
		# Flushed so it lands ahead of notify's stderr lines in the Actions log.
		print(line, flush=True)

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
			"fail_streak": fail_streak,
			"alerted": alerted,
		})

	STATUS.write_text(json.dumps({
		"generated_at": now,
		"targets": results,
	}, indent=2) + "\n")

	all_delivered = True
	for host, state, code, err in transitions:
		# Once one delivery fails the rest almost certainly fail the same way
		# (hub down with the box, or a bad secret), and every further attempt
		# only delays the failure email.
		if not all_delivered:
			print(f"skipped notify-hub for {host} {state}", file=sys.stderr)
		elif not notify(host, state, code, err, now):
			all_delivered = False

	if not all_delivered:
		sys.exit(1)


if __name__ == "__main__":
	main()
