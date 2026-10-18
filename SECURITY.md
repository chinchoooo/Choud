# Security policy

Choud stores people's private files, so security reports are taken seriously.

## Reporting a vulnerability

**Please do not open a public issue for a security problem.**

Use GitHub's private reporting instead: on the repository page open **Security > Report a
vulnerability**. That opens a private advisory only the maintainers can see. Include:

- what you found and where (file, endpoint or screen),
- steps to reproduce it, or a proof of concept,
- what an attacker could do with it,
- the version (`GET /api/instance` shows it, or the release tag).

You will get an acknowledgement and an honest timeline. This is a volunteer-run project, so there is no
service-level promise, but data-loss and authentication problems are handled first. Please give us a
reasonable time to fix the issue before you publish it.

## Supported versions

Only the **latest release** receives fixes. Self-hosters are expected to update (`git pull` then
`bash scripts/deploy.sh`); upgrade notes are in each release.

## What is in scope

The server (`server/`), the storage engine (`engine/`), the web app (`web/`), the Android app
(`android/`), the desktop client (`client/`), the deployment files (`docker-compose.yml`,
`deployment/`, `scripts/`) and the documentation where it gives unsafe advice. Examples: bypassing
login or two-factor, reading or changing another user's files, a share link that reaches more than it
should, the public door exposing the app, path traversal, uploaded content running script in the app's
origin, secrets in logs.

Out of scope: problems that need an already-compromised machine or a malicious server administrator,
denial of service by an authenticated user within their own quota, missing hardening on a machine you
chose to expose without following [`docs/deployment.md`](docs/deployment.md), and issues in third-party
software we only run (PostgreSQL, Caddy, Tailscale, Docker): report those upstream.

## Where the security design is documented

[`docs/security.md`](docs/security.md) describes the model: authentication, authorisation (every file
route filters by owner), the engine boundary (no authentication, never published), filesystem safety,
share links and the two-door design, rate limits and logging. Read it before judging whether something
is a bug or a deliberate trade-off.

## An honest note

Choud has not had an independent security audit. It has a large automated test suite, including tests
for unauthorised access and forged headers, but that is not a substitute. Until it has been audited,
expose it to the internet only as described in the deployment guide (the "shares only" public door), keep
two-factor login on, and use strong passwords.
