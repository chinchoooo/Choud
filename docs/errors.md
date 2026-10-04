# Troubleshooting / FAQ

Real problems hit while setting this up on a fresh Linux Mint server,
with the actual fix for each. If you're self-hosting this project,
these are the errors you're most likely to run into, roughly in the
order you'll hit them.

## Docker install

### `E: Unable to locate package docker-compose-plugin`

Your distro's default APT repos don't carry the Compose v2 plugin.
Install Docker from Docker's own official repo instead of the
distro's `docker.io` package:

```bash
sudo apt remove -y docker.io   # if you already tried this
sudo apt update
sudo apt install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker $USER
```

Log out and back in (or run `newgrp docker`) so your user actually
picks up the new group membership.

### `404 Not Found` fetching a package (e.g. `curl_8.5.0-...`)

Your local APT package index is stale — the mirror rotated out that
exact package version since you last ran `apt update`.

```bash
sudo rm -rf /var/lib/apt/lists/*
sudo apt update
```

### `permission denied while trying to connect to the docker API at unix:///var/run/docker.sock`

Your shell session hasn't picked up your `docker` group membership yet
(`usermod -aG` alone doesn't affect an already-open shell).

```bash
groups                       # confirm "docker" isn't listed
sudo usermod -aG docker $USER
newgrp docker                # applies it without a full logout
docker ps                    # should now work with no sudo
```

## Building the engine

### `CMake Error ... Could NOT find GTest`

The engine's `CMakeLists.txt` always configures its test suite
(`add_subdirectory(tests)`) even when you're only building the
production binary — and the test suite needs GoogleTest, which the
Docker build image never installs (`engine/Dockerfile` only installs
`build-essential cmake libboost-dev libssl-dev`).

Fastest fix — add the missing package to the Dockerfile:

```bash
sed -i 's/build-essential cmake libboost-dev libssl-dev/build-essential cmake libboost-dev libssl-dev libgtest-dev/' engine/Dockerfile
docker compose up -d --build
```

(The cleaner long-term fix is making the test subdirectory optional
in CMake so production builds never need GTest at all — worth doing
if this keeps coming up.)

## Reaching the app from another machine

### `curl`/browser works from the server itself, but times out from your laptop

This is a network-path problem, not a Docker problem — first rule
out the app itself:

```bash
docker compose ps                 # confirm every container is Up
curl http://localhost:80          # test the reverse proxy locally on the server
```

If that works, the containers are fine and the issue is purely
network routing between your laptop and the server. Check, in order:

1. **Firewall**: `sudo ufw status` — if active, `sudo ufw allow 80/tcp 443/tcp 8000/tcp`.
2. **Same network**: your laptop and the server need to actually be
   able to reach each other. `ping <server-ip>` from your laptop — if
   it times out, they're not on the same LAN/hotspot right now.
3. **Different networks entirely** (laptop and server on different
   WiFi/hotspots, e.g. one on a phone hotspot and one on home WiFi):
   plain LAN IPs won't work at all. Use [Tailscale](https://tailscale.com/)
   on both machines and connect via the Tailscale IP instead
   (`tailscale status` to find it), or tunnel over SSH:
   ```bash
   ssh -L 8080:localhost:80 user@server
   # then visit http://localhost:8080 on your own machine
   ```

### The web UI loads, but every API call fails with `ERR_CONNECTION_REFUSED` to `localhost:8000`

The frontend's API base URL defaults to `http://localhost:8000`,
which only works when you're browsing from the *same machine* the
server runs on — from anywhere else, `localhost` means your own
laptop, not the server.

Set it to a relative path instead, so requests go through Caddy's
existing `/api/*` proxy at whatever address you're actually visiting:

```bash
# in .env:
VITE_API_BASE_URL=
```

**Gotcha**: `docker-compose.yml` uses `${VITE_API_BASE_URL:-http://localhost:8000}`
— the `:-` treats an *empty* value the same as *unset* and silently
falls back to the default anyway. An explicitly-empty override needs
a single dash instead:

```bash
sed -i 's/VITE_API_BASE_URL:-http:\/\/localhost:8000/VITE_API_BASE_URL-http:\/\/localhost:8000/' docker-compose.yml
docker compose config | grep VITE_API_BASE_URL   # confirm it now shows empty
docker compose up -d frontend
```

Hard-refresh your browser afterward (`Ctrl+Shift+R`) — a normal
refresh can serve you the old cached JavaScript bundle that still has
the wrong URL baked in.

## First run / database

### `500 Internal Server Error` on register/login — logs show `relation "users" does not exist`

The database container starts empty; nothing runs migrations for you
automatically. Run them once after first bringing the stack up:

```bash
docker compose exec backend alembic upgrade head
```

### Alembic fails partway with `StringDataRightTruncation: value too long for type character varying(32)`

Alembic's own internal `alembic_version` tracking table defaults to a
32-character column, but this project's migration revision names are
longer, descriptive strings (e.g. `0002_add_folders_and_files_tables`)
rather than short hash IDs — so it overflows.

Also note: `alembic upgrade head` runs as **one single transaction**
by default, so if a later migration fails, *everything* from that run
rolls back — including migrations that appeared to succeed first.
Re-running `alembic upgrade head` afterward may then show `does not
exist` errors for tables you thought were already created; that's
expected, nothing is actually left half-applied.

Fix — create the tracking table yourself first, with a wide enough
column, before Alembic gets a chance to create its own (too-narrow)
version:

```bash
docker compose exec postgres psql -U cloud -d personal_cloud -c "
CREATE TABLE alembic_version (
    version_num VARCHAR(255) NOT NULL,
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);
"
docker compose exec backend alembic upgrade head
```

(swap the username/db name if yours differ from `.env`'s
`POSTGRES_USER`/`POSTGRES_DB`)

## Verifying it actually worked

Don't just trust a green checkmark in the UI — you can verify the
whole upload pipeline independently:

```bash
# 1. the database row and its content hash
docker compose exec postgres psql -U cloud -d personal_cloud -c "SELECT id, name, size, content_hash FROM files;"

# 2. the physical object landed on disk, sharded by hash prefix
docker compose exec engine sh -c 'find / -path "*/objects/*" -type f 2>/dev/null'

# 3. the stored bytes actually match the claimed hash
docker compose exec engine sh -c 'sha256sum <path from step 2>'
```

If all three agree, the full API → engine → storage pipeline is
genuinely working, not just reporting success.
