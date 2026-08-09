# print-mcp

A Dockerized MCP server that turns Markdown into print-ready PDFs and submits them to printers managed by CUPS. The MCP endpoint uses a static Bearer token and is published to the internet through a Cloudflare Tunnel.

This guide walks the whole stack from a clean machine: CUPS (printer server), the MCP server (renders + submits jobs), and Cloudflare (public HTTPS endpoint). Follow it top to bottom the first time — a surprising amount of the pain in this project comes from skipping one step, and the biggest single gotcha is the **MCP host allow-list** (step 6).

## Architecture

```text
Remote MCP client -> Cloudflare Tunnel -> print-mcp -> CUPS -> USB or IPP printer
                                                    ^
Tailscale clients -> host Tailscale IP:631 ----------+
```

- `cups` listens on `0.0.0.0:631` *inside* the private compose network. On the host it is published only on `CUPS_BIND_IP:631`.
- `mcp` exposes the MCP HTTP endpoint on port 8000, reachable by `cloudflared` over the private `tunnel-edge` network but by the host only on localhost.
- `cloudflared` runs only when the `tunnel` profile is enabled; it dials out to Cloudflare and needs no inbound ports open.

## Requirements

- A Linux Docker host with a recent Docker Engine + Docker Compose plugin. **Docker Desktop is not supported** (no USB passthrough; host mounts differ).
- For remote CUPS access: Tailscale (or another trusted private interface) on that host.
- For the public MCP URL: a Cloudflare account, a domain on it, and a **named** tunnel (Zero Trust feature).

## Step 1 — Clone and configure

```bash
git clone <your-repo-url> print-mcp && cd print-mcp
cp .env.example .env
```

Generate two independent secrets and paste them into `.env`:

```bash
openssl rand -hex 32    # -> MCP_BEARER_TOKEN
openssl rand -hex 24    # -> CUPS_ADMIN_PASSWORD
```

`.env` is not committed and holds everything the stack needs. The keys are described in `.env.example`; the two that most often trip people up are `CUPS_ALLOWED_NETWORKS` and `MCP_ALLOWED_HOSTS`, covered below.

## Step 2 — Start the base stack

```bash
docker compose up -d --build
```

This starts `cups` and `mcp`. CUPS is reachable at <http://127.0.0.1:631> (admin page at `/admin`) and MCP at <http://127.0.0.1:8000>. Don't start the tunnel yet.

Verify the services are healthy:

```bash
curl -fsS http://127.0.0.1:8000/healthz   # {"status":"ok"}
docker compose ps
```

## Step 3 — Add your printer

Most modern network printers speak **IPP Everywhere / driverless**, so this is the recommended path.

**Automatic (recommended).** Put the printer's static IP in `.env` and the `cups` container configures the queue itself on every start — no manual `lpadmin`, and it reapplies automatically after any rebuild or volume wipe:

```dotenv
# .env
CUPS_PRINTER_IP=192.168.86.32
CUPS_PRINTER_NAME=brother-hl2350dw
```

On boot it creates the `ipp://CUPS_PRINTER_IP/ipp/print` queue (if it doesn't already exist), enables it, and makes it the CUPS default. Set it and let Docker do the rest.

**Manual fallback.** Point the queue at the printer's IPP URI and enable it in one shot:

```bash
# adjust the IP and URI to your printer
docker compose exec cups lpadmin -p brother -E -v ipp://192.168.86.32/ipp/print -m everywhere
docker compose exec cups lpadmin -d brother        # make it the default queue
```

`-m everywhere` asks CUPS to use its built-in driverless/IPP Everywhere model, which auto-detects media, duplex, and color capabilities. Find the IPP URI on the printer's network report or config page; it is usually `ipp://PRINTER_IP:631/ipp/print`.

Prefer a web UI? Open <http://127.0.0.1:631/admin>, sign in with `CUPS_ADMIN_USER` / `CUPS_ADMIN_PASSWORD` (paperclip / admin section), choose *Internet Printing Protocol*, and enter the `ipp://` URI.

USB printers need the USB overlay: `docker compose down`, then `docker compose -f compose.yaml -f compose.usb.yaml up -d --build`, which exposes only the Linux USB bus to CUPS. Replugging a device may require restarting the CUPS service.

If calls should not have to name a printer, set `DEFAULT_PRINTER` in `.env` to the queue name. Queue config and job history persist in named Docker volumes.

## Step 4 — Quick test

The print CLI is baked into the `mcp` image, so a smoke test needs no mounts:

```bash
echo 'This is a quick test of the Print MCP stack.' | docker compose exec -T mcp \
  python /app/cli/print_file.py - --page-size a4
```

Expected: `rendered /tmp/stdin.pdf (1 pages)` then `submitted job N to printer '...'`. See the [CLI](#cli) section for all options.

## Step 5 — (Optional) Remote CUPS over Tailscale

To manage printers from another machine, publish CUPS only on this host's Tailscale IP:

```bash
tailscale ip -4
```

```dotenv
# .env
CUPS_BIND_IP=100.100.20.30
CUPS_ALLOWED_NETWORKS=100.64.0.0/10
```

Then `docker compose up -d`. Other tailnet machines can browse <http://100.100.20.30:631> and add a queue using `ipp://100.100.20.30:631/printers/QUEUE_NAME`.

`CUPS_ALLOWED_NETWORKS` is a comma-separated list of IPs/CIDRs allowed to browse and print. Keep `CUPS_BIND_IP` on localhost or a private interface; **never** use `0.0.0.0` unless a host firewall independently limits port 631. Administration and job cancellation always require the admin credentials; printing/queries do not.

## Step 6 — Publish MCP through Cloudflare Tunnel

This is where the biggest mistake in this project lives: **if you don't add your public hostname to `MCP_ALLOWED_HOSTS`, the tunnel forwards traffic fine but the MCP server rejects every request with HTTP 421 `Invalid Host header`.** The tunnel looks healthy while nothing works.

### In Cloudflare Zero Trust

1. Create a **named tunnel** (Zero Trust → Networks → Tunnels → Create a tunnel). Choose the Cloudflare connector type.
2. Create a **public hostname** for `TUNNELED_HOSTNAME.example` whose service URL is exactly:

   ```text
   http://mcp:8000
   ```

   The hostname is resolved from inside the compose network, so `mcp` works even though port 8000 is otherwise bound to localhost. Note: if `MCP_ALLOWED_HOSTS` is not set, this same hostname is what the server checks — keep the two in sync exactly (protocol and port are ignored, hostname is not).
3. Copy the connector token (the long `eyJ...` string) into `.env`.

```dotenv
# .env
CLOUDFLARE_TUNNEL_TOKEN=eyJhIjoi...
MCP_ALLOWED_HOSTS=TUNNELED_HOSTNAME.example
```

`MCP_ALLOWED_HOSTS` accepts a comma-separated list. Only hostnames already in the list pass the server's DNS-rebinding protection; localhost and `mcp` are allowed by default for local testing.

### Start the tunnel profile

```bash
docker compose --profile tunnel up -d --build
```

The public endpoint is `https://TUNNELED_HOSTNAME.example/mcp`.

### Quick remote check

From outside (or with curl on the host):

```bash
curl -fsS https://TUNNELED_HOSTNAME.example/healthz
```

Not a 2xx? Start with `docker compose logs cloudflared` to confirm the connector is up and forwarding the URL, then re-check that `MCP_ALLOWED_HOSTS` exactly matches the hostname in the URL you're hitting.

## MCP URL and auth

Endpoint: `https://TUNNELED_HOSTNAME.example/mcp` (or `http://127.0.0.1:8000/mcp` locally).

Every `/mcp` request must send your `MCP_BEARER_TOKEN` in any one of these forms, checked in order:

1. `Authorization: Bearer <token>` (the standard form — preferred)
2. `Authorization: <token>` (raw token, no scheme)
3. `X-API-Key: <token>`
4. `X-Auth-Token: <token>`
5. `X-MCP-Token: <token>`
6. A query parameter `token`, `access_token`, `api_key`, or `mcp_token`

```text
Authorization: Bearer YOUR_MCP_BEARER_TOKEN
```

```bash
curl -fsS -H "Authorization: Bearer $MCP_BEARER_TOKEN" \
  https://TUNNELED_HOSTNAME.example/mcp -X POST -d '{}'
```

The alternate transports exist for proxies / TLS terminators (some Cloudflare or forward-proxy setups) that rewrite or strip `Authorization`. Use whichever survives the path from client to container; the bearer header is the most secure. If you ever set `MCP_ALLOWED_ORIGINS`, the `Origin` header is validated too.

The CLI honors the same token. `MCP_BEARER_TOKEN` (server auth) and `CLOUDFLARE_TUNNEL_TOKEN` (tunnel identity) are separate secrets; rotate either in `.env` and recreate only the affected service.

## CLI

The simplest way to print from the host is to run the CLI inside the running `mcp` container — `docker exec` bypasses the server entrypoint and inherits CUPS, the default queue, and secrets:

```bash
# Markdown from a pipe (no file inside the container required)
cat notes.md | docker compose exec -T mcp python /app/cli/print_file.py -

# Options
docker compose exec -T mcp python /app/cli/print_file.py notes.md \
  --page-size a4 --orientation portrait \
  --margins-mm 12 --copies 2 \
  --sides two-sided-long-edge --color mono
```

`file` is a path inside the container or `-` for stdin. A path writes the rendered PDF next to the source; stdin writes to the container temp dir. Flags:

| Flag | Default | Meaning |
| --- | --- | --- |
| `--printer` | settings/default | CUPS queue name |
| `--title` | file name or `stdin` | job title |
| `--page-size` | `letter` | `letter`, `legal`, `a4` |
| `--orientation` | `portrait` | `portrait`, `landscape` |
| `--margins-mm` | `DEFAULT_MARGIN_MM` | uniform margins in mm |
| `--copies` | `1` | number of copies |
| `--sides` | `one-sided` | `one-sided`, `two-sided-long-edge`, `two-sided-short-edge` |
| `--color` | `auto` | `auto`, `color`, `mono`/`monochrome` |

There is also `bin/print-md.sh`, a thin wrapper that mounts the source directory so you can pass any absolute path:

```bash
./bin/print-md.sh --page-size a4 ./docs/report.md
```

## MCP tools

- `list_printers()` returns every configured CUPS queue and its current capabilities.
- `print_markdown(markdown, title?, printer?, page_size?, orientation?, margins?, copies?, sides?, color_mode?)` renders and submits a document. Standard paper sizes are `letter`, `legal`, and `a4`.
- `get_job_status(job_id)` returns the state and timestamps retained by CUPS.

Raw HTML is disabled. Markdown images may use public HTTP/HTTPS URLs or data URIs. Private, loopback, link-local, multicast, and reserved destinations are rejected, including after redirects. External images are downloaded and validated before PDF rendering; a failed image prevents submission.

## Health and troubleshooting

```bash
curl http://127.0.0.1:8000/healthz
curl http://127.0.0.1:8000/readyz
docker compose logs cups mcp cloudflared
```

`/healthz` checks the MCP process. `/readyz` returns 503 until CUPS has at least one configured queue. Neither exposes document or credential data.

| Symptom | Fix |
| --- | --- |
| HTTP 421 `Invalid Host header` via the tunnel, but works on localhost | `MCP_ALLOWED_HOSTS` in `.env` does not (exactly) contain the public hostname you're hitting. Update it and `docker compose up -d mcp`. |
| Tunnel up but no requests traced | Confirm the tunnel is actually running (`docker compose --profile tunnel ps`) and the public hostname maps to `http://mcp:8000`; check route precedence in Cloudflare so a Worker doesn't shadow the tunnel. |
| `cupsdDoSelect() failed - Bad address!`, cups keeps crashing | Docker ≥27.3 sets an enormous `nofile` ulimit that overflows CUPS's `select()`. The entrypoint already applies `ulimit -n 65535`; if you see this, confirm you rebuilt (`--build`) and aren't bypassing `entrypoint.sh`. |
| CUPS can't discover a network printer | Add it by explicit IPP URI; multicast discovery does not reliably cross Docker or Tailscale networks. Reserve the printer's LAN address in DHCP. |
| `ipps://` printer with a private certificate | Install its CA in the CUPS image instead of disabling TLS validation. |
| Unsupported duplex/color/media option | MCP returns `UNSUPPORTED_OPTION` without submitting the job. |

## Development

```bash
uv sync --extra dev
uv run ruff check .
uv run pytest
docker compose config
```
