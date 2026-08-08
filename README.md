# print-mcp

A Dockerized MCP server that turns Markdown into print-ready PDFs and submits them to printers managed by CUPS. The MCP endpoint uses a static Bearer token and can be published through the included Cloudflare Tunnel service.

## Architecture

```text
Remote MCP client -> Cloudflare Tunnel -> print-mcp -> CUPS -> USB or IPP printer
                                                    ^
Tailscale clients -> host Tailscale IP:631 ----------+
```

CUPS and MCP communicate on a private Compose network. Cloudflare can reach only MCP. CUPS port 631 is published on the exact host address configured by `CUPS_BIND_IP`; it defaults to localhost.

## Requirements

- A Linux Docker host with Docker Compose.
- For remote CUPS access, Tailscale or another trusted private interface on that host.
- For the public MCP URL, a Cloudflare account, domain, named tunnel, and tunnel token.
- USB printers require access to `/dev/bus/usb`; Docker Desktop hosts are not supported for USB passthrough.

## Quick start

Clone the repo, create the environment file, and replace both secrets:

```bash
cp .env.example .env
openssl rand -hex 32        # paste into MCP_BEARER_TOKEN
openssl rand -hex 32        # paste into CUPS_ADMIN_PASSWORD
docker compose up -d --build
```

### Add your printer

Most modern network printers speak **IPP Everywhere / driverless**, so this is the recommended path. Point the queue at the printer's IPP URI and enable it in one shot — no web UI, no driver PPD:

```bash
# adjust the IP and URI to your printer
docker compose exec cups lpadmin -p brother -E -v ipp://192.168.1.50/ipp/print -m everywhere
docker compose exec cups lpadmin -d brother        # make it the default queue
```

`-m everywhere` asks CUPS to use its built-in driverless/IPP Everywhere model, which auto-detects media, duplex, and color capabilities. Find the IPP URI on the printer's network report or config page; it is usually `ipp://PRINTER_IP:631/ipp/print`.

If you prefer the web UI, open <http://127.0.0.1:631/admin>, sign in with `CUPS_ADMIN_USER` and `CUPS_ADMIN_PASSWORD`, choose Internet Printing Protocol, and enter the `ipp://` URI.

USB printers need extra setup: stop the stack and restart with the USB overlay.

```bash
docker compose down
docker compose -f compose.yaml -f compose.usb.yaml up -d --build
```

The overlay exposes the Linux USB bus only to CUPS. Replugging a device may require restarting the CUPS service. Add the discovered printer in the same CUPS admin page.

Set `DEFAULT_PRINTER` to the queue name if calls should not have to select a printer. Queue configuration and job history persist in Docker volumes.

### Quick test (docker exec)

The CLI is baked into the `mcp` image, so a quick print needs no special mounts. Pipe Markdown to it and give the printer a moment:

```bash
echo 'This is a quick test of the Print MCP stack.' | docker compose exec -T mcp python /app/cli/print_file.py - --page-size a4
```

Expected output: `rendered /tmp/stdin.pdf (1 pages)` then `submitted job N to printer '...'`. The job should complete on the printer within a few seconds.

## CLI

The easiest way to print a file from the host is to run the same script inside the running `mcp` container. `docker exec` bypasses the server entrypoint and inherits the container's environment (CUPS server, default queue, secrets), so no extra configuration is needed.

```bash
# Markdown from a pipe (no file inside the container required)
cat notes.md | docker compose exec -T mcp python /app/cli/print_file.py -

# Options
docker compose exec -T mcp python /app/cli/print_file.py notes.md \
  --page-size a4 --orientation portrait \
  --margins-mm 12 --copies 2 \
  --sides two-sided-long-edge --color mono
```

`file` accepts a path inside the container or `-` to read from standard input. If the source is a real path, the rendered PDF is written next to it; for stdin input it is written to the container temp dir. Flags:

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

For host-friendly use there is also a thin `bin/print-md.sh` wrapper that mounts the source directory so you can pass any file by absolute path:

```bash
./bin/print-md.sh --page-size a4 ./docs/report.md
```

## Tailscale CUPS access

Find the host's Tailscale IPv4 address and set it as the only published CUPS address:

```bash
tailscale ip -4
```

```dotenv
CUPS_BIND_IP=100.100.20.30
CUPS_ALLOWED_NETWORKS=100.64.0.0/10
```

Restart with `docker compose up -d`. Other tailnet machines can browse the web interface at `http://100.100.20.30:631` and add a queue using:

```text
ipp://100.100.20.30:631/printers/QUEUE_NAME
```

`CUPS_ALLOWED_NETWORKS` accepts a comma-separated list of IP addresses or CIDRs. Keep `CUPS_BIND_IP` on localhost or a private interface; never use `0.0.0.0` unless a host firewall independently limits port 631. CUPS administration always requires the configured administrator credentials. Printing and printer/job queries are allowed from the configured networks so operating-system print clients work normally; job cancellation and configuration require authentication.

## Cloudflare Tunnel

Everything ships in `compose.yaml`; only the two secrets need filling in `.env`:

- `MCP_BEARER_TOKEN` — the static token every `/mcp` request must send. Generate with `openssl rand -hex 32`.
- `CLOUDFLARE_TUNNEL_TOKEN` — the connector token from a named tunnel (Cloudflare Zero Trust → Networks → Tunnels).

In Cloudflare Zero Trust, create a named tunnel and a public hostname whose service URL is:

```text
http://mcp:8000
```

Put the connector token in `.env`, then start the tunnel profile:

```dotenv
CLOUDFLARE_TUNNEL_TOKEN=your-named-tunnel-token
MCP_ALLOWED_HOSTS=your-hostname.example
```

```bash
docker compose --profile tunnel up -d --build
```

Because `mcp` is also on the `tunnel-edge` network, `cloudflared` reaches it at `http://mcp:8000` even though port 8000 is otherwise bound only to localhost.

### MCP URL and auth

The MCP endpoint is `https://your-hostname.example/mcp`, reached through the tunnel. Configure the client to send the bearer token on every request:

```text
Authorization: Bearer YOUR_MCP_BEARER_TOKEN
```

This mirrors the CLI: the server binary (`print-mcp`, started by the `mcp` service) enforces the same `MCP_BEARER_TOKEN` from `.env`, so the token is defined in one place for both the tunnel-facing MCP server and the local CLI. The Cloudflare tunnel token and MCP bearer token are separate secrets; rotate either by editing `.env` and recreating only the affected service.

## MCP tools

- `list_printers()` returns every configured CUPS queue and its current capabilities.
- `print_markdown(markdown, title?, printer?, page_size?, orientation?, margins?, copies?, sides?, color_mode?)` renders and submits a document. Standard paper sizes are `letter`, `legal`, and `a4`.
- `get_job_status(job_id)` returns the state and timestamps retained by CUPS.

Raw HTML is disabled. Markdown images may use public HTTP/HTTPS URLs or data URIs. Private, loopback, link-local, multicast, and reserved destinations are rejected, including after redirects. External images are downloaded and validated before PDF rendering; a failed image prevents submission.

## Health and troubleshooting

```bash
curl http://127.0.0.1:8000/healthz
curl http://127.0.0.1:8000/readyz
docker compose logs cups mcp
```

`/healthz` checks the MCP process. `/readyz` returns 503 until CUPS has at least one configured queue. Neither endpoint exposes document or credential data.

- If CUPS cannot discover a network printer, add it by explicit IPP URI; multicast discovery does not reliably cross Docker or Tailscale networks.
- Reserve the printer's LAN address in DHCP so its URI remains stable.
- For an `ipps://` printer with a private certificate, install its CA in the CUPS image instead of disabling TLS validation.
- If a requested duplex, color, or media option is unsupported, MCP returns `UNSUPPORTED_OPTION` without submitting the job.

## Development

```bash
uv sync --extra dev
uv run ruff check .
uv run pytest
docker compose config
```
