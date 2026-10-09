#!/usr/bin/env python3
"""Probe each target in targets.toml, write status.json, post Discord
notifications on state transitions. Runs inside .github/workflows/probe.yml.

Previous status comes from the live site (fetched by the workflow before this
script runs), so state transitions survive across runs without the workflow
having to commit anything back to the repo.
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

REPO = Path(__file__).resolve().parent
TARGETS = REPO / "targets.toml"
STATUS = REPO / "status.json"
DISCORD_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")

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


def notify(message: str) -> None:
	if not DISCORD_URL:
		print(f"(DISCORD_WEBHOOK_URL unset; would send: {message})")
		return
	body = json.dumps({"content": message}).encode()
	req = urllib.request.Request(
		DISCORD_URL,
		data=body,
		method="POST",
		headers={"Content-Type": "application/json"},
	)
	try:
		urllib.request.urlopen(req, timeout=TIMEOUT)
	except Exception as e:
		print(f"Discord notify failed: {e}", file=sys.stderr)


def load_previous() -> dict[str, dict]:
	if not STATUS.exists():
		return {}
	try:
		data = json.loads(STATUS.read_text())
	except Exception:
		return {}
	return {t["host"]: t for t in data.get("targets", [])}


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
		})

		prev_state = prev.get("state")
		if prev_state and prev_state != state:
			transitions.append((host, state, code, err))

	STATUS.write_text(json.dumps({
		"generated_at": now,
		"targets": results,
	}, indent=2) + "\n")

	for host, state, code, err in transitions:
		if state == "down":
			detail = f"HTTP {code}" if code else (err or "no response")
			notify(f":red_circle: **{host}** is down ({detail}).")
		else:
			notify(f":green_circle: **{host}** recovered.")


if __name__ == "__main__":
	main()
