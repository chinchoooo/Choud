# Deployment

## Local development

```bash
cp .env.example .env
make docker-up
```

This runs `docker compose up -d --build`, starting PostgreSQL, the C++
engine, the FastAPI backend, the React frontend (Vite dev server), and a
Caddy reverse proxy. See [`docker-compose.yml`](../docker-compose.yml).

**On a fresh database, apply migrations before using the app** — the
containers starting up does not create any tables:

```bash
make docker-migrate
```

Verify with:

```bash
./scripts/healthcheck.sh
```

Accessing the app from a different machine than the one running Docker
(LAN, Tailscale, a real domain)? Set `VITE_API_BASE_URL=` (empty) in
`.env` instead of leaving the `localhost` default — see
[`errors.md`](errors.md) for why, and for other real problems people
hit during first-time setup.

## Networking

- The C++ engine is never published to the host — only `backend` can
  reach it, over the Docker-internal network (see
  [`security.md`](security.md#the-engine-boundary)).
- `postgres`, `backend`, `engine`, and `frontend` are only reachable
  from the reverse proxy and each other inside the Compose network;
  `backend` and `frontend` are also published directly for local
  development convenience.
- Caddy (`deployment/Caddyfile`) fronts everything on `:80`/`:443`,
  routing `/api/*` and `/s/*` to the backend and everything else to the
  frontend.

## Deploying to real hardware (Phase 9)

The target is a repurposed Linux laptop on the LAN, reachable remotely
over Tailscale — not a router port-forward.

1. Install Docker and the Docker Compose plugin.
2. Clone the repository, copy `.env.example` to `.env`, and fill in real
   secrets (`JWT_SECRET`, database credentials).
3. Prefer a wired Ethernet connection for the server.
4. `docker compose up -d --build`.
5. Install [Tailscale](https://tailscale.com/) on the server and on
   client devices; access the server at its Tailscale address.
6. Optionally install the provided systemd unit so the stack starts on
   boot:

   ```bash
   sudo cp deployment/systemd/personal-cloud.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now personal-cloud
   ```

   (Edit `WorkingDirectory` in the unit file to match where the repo is
   checked out.)

## Backups

```bash
./scripts/backup.sh            # writes backups/<timestamp>/
./scripts/restore.sh <backup-dir>
```

`backup.sh` dumps the PostgreSQL database and archives the object
storage volume (via the running `engine` container) into a timestamped
directory. `restore.sh` reverses this — it **overwrites** the current
database and storage, so it prompts for confirmation.

A backup that has never been restored is just a particularly optimistic
pile of files: periodically test `restore.sh` against a scratch
environment. Full backup/restore hardening (retention, encryption at
rest, automated scheduling) is Phase 10 work.

## Health monitoring

`GET /api/health` (see [`api.md`](api.md)) reports the status of the API,
database, engine, and storage in one call — suitable for an external
uptime check or a cron job running `scripts/healthcheck.sh`.