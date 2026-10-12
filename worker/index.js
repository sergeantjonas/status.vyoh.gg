// Cron-only Worker that starts probe.yml via workflow_dispatch, because
// GitHub's own schedule trigger slips by hours on free-tier public repos.

const DISPATCH_URL =
	'https://api.github.com/repos/sergeantjonas/status.vyoh.gg/actions/workflows/probe.yml/dispatches';

export default {
	async scheduled(_controller, env) {
		const res = await fetch(DISPATCH_URL, {
			method: 'POST',
			headers: {
				Authorization: `Bearer ${env.GITHUB_TOKEN}`,
				Accept: 'application/vnd.github+json',
				'X-GitHub-Api-Version': '2022-11-28',
				// Workers' fetch sends no User-Agent and GitHub rejects requests without one.
				'User-Agent': 'status.vyoh.gg trigger (+https://github.com/sergeantjonas/status.vyoh.gg)',
			},
			body: JSON.stringify({ ref: 'main' }),
		});
		// Throwing marks the invocation failed in the Worker's cron event log.
		if (!res.ok) throw new Error(`dispatch failed: ${res.status} ${await res.text()}`);
	},
};
