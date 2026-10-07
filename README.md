# status.vyoh.gg

One page that says whether each public site on the shared VPS answers, plus an alert when one stops.

- **Live:** <https://status.vyoh.gg> (GitHub Pages).
- **Prober:** systemd timer on the box the page watches.
- **Alerts:** [healthchecks.io](https://healthchecks.io), out of band from the box.

The page is static HTML and JS with no build step and no dependencies. It reads badge JSON from healthchecks.io straight from the browser; the endpoint answers `Access-Control-Allow-Origin: *`, so no backend sits between them.

Planning and decisions live under [docs/working-notes/](docs/working-notes/). The cross-project constraint ("the box cannot watch itself") lives in [commonplace](https://github.com/sergeantjonas/commonplace/blob/main/status-page.md), since the same rule applies to anything else that reports on the box.
