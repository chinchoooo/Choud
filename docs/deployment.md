# Deployment

This is the guide for running the **server** (everything in
[`docker-compose.yml`](../docker-compose.yml)) on a real machine — typically a
spare Linux laptop — and reaching it from your other devices over
[Tailscale](https://tailscale.com/). The desktop and phone sync **clients**
run on your devices and talk to this server over HTTP; they are not part of
this stack.

```text
 your laptop/phone ──(Tailscale, WireGuard-encrypted)──▶ server machine
                                                         │
                                                  Caddy  :80   ← the ONLY published port
                                                  ├─ /api/*, /s/* ─▶ backend (FastAPI)  ─▶ postgres
                                                  └─ everything else ─▶ frontend (nginx)    └▶ engine (C++) ─▶ storage volume
```

## Quick start (Linux server)

You need: Docker Engine + the Compose v2 plugin, `git`, `curl`, ~5 GB free
disk and ~2 GB free RAM for the first build (it compiles the C++ engine).

```bash
# 1. Docker (Ubuntu / Mint) — skip if `docker compose version` already works
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"      # then log out and back in

# 2. Get the code
git clone https://github.com/bored-arvi/Choud.git personal-cloud
cd personal-cloud

# 3. Generate .env with strong random secrets (never overwrites an existing one)
scripts/setup.sh

# 4. Check the machine, build, start, wait until healthy
scripts/deploy.sh
```

`scripts/deploy.sh` runs `scripts/preflight.sh` first and stops with a
`[FAIL]` line if something is wrong (Docker not running, placeholder secrets,
port in use, CRLF line endings, low disk…). When it finishes it prints the
URL to open. **The first build takes several minutes**; later ones are
cached.

Then:

```bash
# 5. Remote access
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up                    # log in; do the same on your other devices
tailscale ip -4                      # the address to use from other devices

# 6. Start on boot + nightly backup + health check (optional but recommended)
sudo deployment/scripts/install-systemd.sh
```

Open `http://<tailscale-ip>` from any device on your tailnet, register the
first account, and you are in. Traffic is encrypted by Tailscale between
devices, so plain HTTP on the tailnet is fine; see
[HTTPS](#https-optional) if you want a certificate anyway.

> **Back up `.env`.** It holds `JWT_SECRET` and `POSTGRES_PASSWORD`. Losing the
> password makes the existing database unreadable. `scripts/backup.sh` copies
> it into every backup for exactly this reason.

## What is exposed

- Only the **Caddy reverse proxy** publishes ports (`HTTP_PORT`, default 80,
  and `HTTPS_PORT`, default 443). Postgres, the engine, the backend and the
  web container are reachable only on the internal Docker network.
- The C++ engine has no authentication by design — it must never be
  published ([`security.md`](security.md#the-engine-boundary)).
- The stack **refuses to start with placeholder secrets**: compose requires
  `POSTGRES_PASSWORD` and `JWT_SECRET`, and the backend itself exits in
  production if either is a placeholder or `JWT_SECRET` is shorter than 32
  characters.
- Auth endpoints are rate limited per client IP (login 10/min, register
  10/hour). The IP comes from the `X-Forwarded-For` header Caddy sets, so
  keep the backend unpublished (the default).

## Making a laptop a good server

A laptop is built to sleep. Tell it not to:

```bash
# Keep running with the lid closed and never suspend
sudo sed -i 's/^#\?HandleLidSwitch=.*/HandleLidSwitch=ignore/; s/^#\?HandleLidSwitchExternalPower=.*/HandleLidSwitchExternalPower=ignore/' /etc/systemd/logind.conf
sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target
sudo systemctl restart systemd-logind
```

- Use **Ethernet**, not Wi-Fi, and give the machine a fixed address (a DHCP
  reservation in your router) so you can always find it on the LAN.
- In the BIOS/UEFI, enable **"restore on AC power loss"** (or "power on after
  power failure") if the option exists. The battery acts as a small UPS; a
  full outage still needs the machine to turn itself back on.
- Keep it ventilated and on mains power. Check the temperature occasionally
  (`sensors` from the `lm-sensors` package); a hot, dusty laptop is the usual
  first failure.
- Run **one disk** only if you must, but see [Backups](#backups): a single
  disk is a single point of failure, and a second copy somewhere else is not
  optional.
- A firewall is optional because only port 80/443 are published, but if you
  use `ufw`: `sudo ufw allow in on tailscale0` and allow your LAN if wanted.

## Updating

```bash
git pull
scripts/deploy.sh          # rebuilds what changed, restarts, waits for healthy
```

Database migrations run automatically every time the backend container starts
(`server/entrypoint.sh` → `server/scripts/migrate.sh`); if one fails the
container stops instead of serving a mismatched schema — look at
`docker compose logs backend`. Take a [backup](#backups) before an update that
adds migrations.

**Rolling back:** `git checkout <previous-tag-or-commit>` then
`scripts/deploy.sh`. Migrations only move forward, so if the new version
changed the schema, restore the pre-update backup too
(`scripts/restore.sh backups/<timestamp>`).

## Backups

```bash
scripts/backup.sh                       # backups/<UTC timestamp>/
scripts/restore.sh backups/<timestamp>  # asks for confirmation (--yes to skip)
```

A backup contains **both** halves, which are useless apart:

| File | Contents |
| --- | --- |
| `database.sql` | `pg_dump` of all metadata (users, folders, files, versions, trash) |
| `storage.tar` | the content-addressed object store (the actual bytes) |
| `.env` | the secrets the stack was running with |
| `SHA256SUMS` | checked by `restore.sh`; a damaged backup is refused |

`backup.sh` writes to a temporary directory and only renames it into place
after checking the dump is complete and the archive is readable, so a failed
run never leaves something that looks like a good backup. It keeps the newest
`BACKUP_KEEP` (default 14).

**A backup on the same disk as the data is not a backup.** Set in `.env`:

```bash
BACKUP_COPY_TO=/media/usb-drive/personal-cloud-backups   # an external drive or network share
BACKUP_KEEP=14
```

The script warns loudly when `BACKUP_COPY_TO` is unset. For off-site copies,
point it at a folder that something like `restic`/`rclone` syncs elsewhere.

`sudo deployment/scripts/install-systemd.sh` schedules `scripts/backup.sh`
nightly at 03:15 (`Persistent=true`: if the laptop was off, it runs at the next
boot). Check with `systemctl list-timers 'personal-cloud*'`.

**Test the restore.** The restore path was verified end to end — back up, wipe
all volumes, restore — and brought back byte-identical files, version history
and folders. Do the same once on your own hardware before trusting it
(see [Verifying in isolation](#verifying-in-isolation)).

## Monitoring

`GET /api/health` reports the API, database, engine and storage in one call
and returns `503` when any is down.

- `scripts/healthcheck.sh` checks it through the proxy (exit code 0/1).
- The systemd health timer runs it every 5 minutes, first asking Docker to
  bring any stopped container back; failures show in
  `journalctl -u personal-cloud-health`.
- Containers have `restart: unless-stopped`, so a crashed process restarts on
  its own.
- Abandoned chunked-upload sessions are cleaned up automatically by an
  in-process job (hourly, `MAINTENANCE_INTERVAL_SECONDS`).

## HTTPS (optional)

Between your devices Tailscale already encrypts everything, so HTTP over the
tailnet is safe. If you want a browser-trusted certificate anyway, enable
MagicDNS and HTTPS in the Tailscale admin console, then:

```bash
sudo tailscale cert <machine>.<tailnet>.ts.net
```

and serve it from Caddy (replace `:80` in `deployment/Caddyfile` with the
hostname and mount the certificate), or let Caddy obtain one automatically if
you own a public domain pointing at the server.

## Development

```bash
make dev        # Vite hot reload, ports on 127.0.0.1, placeholder secrets (.env.dev)
                # open http://localhost:8080 (proxy) or http://localhost:5173 (Vite)
make test       # backend + engine tests
make lint
```

`make dev` uses [`docker-compose.dev.yml`](../docker-compose.dev.yml) and
[`.env.dev`](../.env.dev). Those secrets are public placeholders and the
backend only accepts them with `ENVIRONMENT=development`.

## Verifying in isolation

You can build and exercise the whole stack **without touching a running
deployment** by giving it its own Compose project name, ports and secrets:

```bash
cat > /tmp/verify.env <<EOF
POSTGRES_PASSWORD=$(openssl rand -hex 32)
JWT_SECRET=$(openssl rand -hex 32)
HTTP_PORT=18080
HTTPS_PORT=18443
EOF
docker compose --env-file /tmp/verify.env -p pcverify up -d --build
curl http://localhost:18080/api/health
# ...try things...
docker compose --env-file /tmp/verify.env -p pcverify down -v    # removes ONLY this project's volumes
```

The project name (`-p pcverify`) gives it separate containers, network and
volumes, so it cannot clash with the real stack. To run the backup scripts
against it: `COMPOSE_PROJECT_NAME=pcverify COMPOSE_ENV_FILES=/tmp/verify.env scripts/backup.sh`.

## Troubleshooting

[`errors.md`](errors.md) lists real problems hit while setting this up and
their fixes — read it before debugging a failed `docker compose up` from
scratch. `scripts/preflight.sh` catches most of them up front.

## Alerts and garbage collection (Phase 15)

**Failure alerts.** Set `ALERT_WEBHOOK_URL` in `.env` to an [ntfy](https://ntfy.sh) topic URL
(pick a long, secret topic name and subscribe in the ntfy phone app), a Discord webhook or a Slack
webhook. The 5-minute health timer and the nightly backup then message you when something
fails, and again when it recovers. They speak only on *changes*: one alert when a check starts
failing, one reminder per `ALERT_REMINDER_HOURS` (default 24) while it keeps failing, one
"recovered" message. A backup with no second copy (`BACKUP_COPY_TO` missing or unmounted) also
raises an alert, because that is not really a backup. Delivery problems never make the script fail.
Try it: `ALERT_WEBHOOK_URL=... scripts/healthcheck.sh` while the stack is stopped.

**Garbage collection.** Purging a file already frees the bytes only it used. What GC finds are
orphans from things that went wrong half way (a failed delete, an abandoned upload's chunks, staging
copies from a crash). `scripts/gc.sh` only *reports* by default; `scripts/gc.sh --delete` removes
them. Nothing referenced by any file or version of any user is ever removed (trash included), and
nothing younger than 72 hours (`GC_GRACE_HOURS`), because an upload stores its bytes just before its
database row is saved. The backend also reports once a day on its own; set
`GC_DELETE_ENABLED=true` to let that daily pass delete too.

## Making share links public

Share links point at your server's address. If that is a Tailscale address, only people on your
tailnet can open them. To let **anyone** open a share link without exposing the rest of Choud, run
one command on the server:

```bash
scripts/enable-public-links.sh                     # Tailscale Funnel (free, no domain needed)
scripts/enable-public-links.sh --cloudflare links.example.com   # a Cloudflare Tunnel on your domain
scripts/enable-public-links.sh --status            # what is on right now; changes nothing
scripts/enable-public-links.sh --off               # back to private-only links
scripts/enable-public-links.sh --dry-run           # show what it would do (works with any option)
scripts/enable-public-links.sh --no-verify         # switch it on without the outside check (see below)
```

It checks the public door on this machine, starts the tunnel, checks the public address answers,
writes `PUBLIC_BASE_URL` into `.env` (keeping `.env.bak`) and restarts **only the backend** (a few
seconds; the proxy and engine stay up). If something outside the script has to be done first (turn on
HTTPS certificates or Funnel in the Tailscale admin console, run `cloudflared tunnel login`), it says
exactly what and stops with exit code 2 without changing anything.

The outside check asks a public DNS resolver where your address points and connects to *that*
address, the way a stranger's phone would. (A machine usually cannot reach its own Tailscale address
through the tunnel, so opening the address normally from the server itself fails even when links work
for everyone else.) If the check cannot confirm it, the script prints `tailscale funnel status`; when
that lists your address with `Funnel on`, open `https://<your address>/s/_health` from a phone on
mobile data and, if it shows `{"ok":true,"door":"public",...}`, run the script again with
`--no-verify`.

What is reachable from the internet: **only `/s/*`**, the share pages. The stack runs a second,
**public door**: Caddy listens on `127.0.0.1:8081` (this machine only) and the app, the API and login
answer 404 there, so the tunnel never exposes your drive. It reads the visitor's address from the
rightmost `X-Forwarded-For` entry (what your tunnel saw), so per-visitor rate limits cannot be dodged
with a forged header. Requests through the public door carry an `X-Choud-Door: public` marker the
private door strips, which is what the pause switch below keys on.

**Pause, check, revoke** (Server page in the web app, administrator only):

- *Pause public links* is an instant kill switch: the public door answers 404 for every share link
  while the private door keeps working. *Resume* turns it back on. No restart, no `.env` edit.
- *Check from outside* asks the server to open its own public address like a stranger would.
- *Revoke all my links* (also available to every user) makes every link you created stop working.

The web and phone apps tell the truth about each link: when no public address is set, the share dialog
says the link only works on your private network, and the phone offers to **send the file itself**
instead.

Manual setup, if you prefer: run `sudo tailscale funnel --bg --https=443 http://127.0.0.1:8081` (or
`cloudflared tunnel --url http://127.0.0.1:8081`), put the address in `.env` as
`PUBLIC_BASE_URL=https://...` (no trailing slash) and run `docker compose up -d --no-deps backend`.

Check from a phone that is **not** on Tailscale: open a share link, and also open
`<public address>/api/health`, which must say "Not found". Use an expiry and a password on links to
sensitive folders, and prefer view-only links; edit and file-request links accept uploads from the
internet (limited by your quota and the rate limits). If every visitor shows the same address in
`<public address>/s/_health` (`client_ip`), your tunnel is not passing the visitor's address and the
per-visitor rate limits share one bucket.

## Using Choud from anywhere (without Tailscale on every device)

By default you need Tailscale on every device, and nothing at home is reachable from the internet.
That is the safest setup. If you want the phone and browsers to work anywhere with no VPN:

1. Put your public address in `.env` as `PUBLIC_BASE_URL` (see above) and point a tunnel at the public
   door (`127.0.0.1:8081`).
2. Set `PUBLIC_DOOR_MODE=full` in `.env` and redeploy. The public door then serves the whole app
   instead of just share pages. **Do this only after:** turning on two-factor login for every
   account, using strong passwords, and keeping `REGISTRATION_MODE=invite`.
3. In the phone app, sign in with your private address as usual and, under "More options", add the
   public address. The app tries the private address first (fast, at home or on Tailscale) and falls
   back to the public one by itself, so there is nothing to switch.

Back to share-pages-only at any time by setting `PUBLIC_DOOR_MODE=shares` and redeploying.
