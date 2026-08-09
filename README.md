# print-mcp

**Now your agent can print.**

`print-mcp` is a local MCP server that turns Markdown into a print-ready PDF and sends it to a printer on your local network. Run it next to the printer, optionally open it to the internet with a Cloudflare Tunnel, and connect any MCP-compatible agent to it.

Your agent can then:

- Discover the printers configured on your machine.
- Print Markdown with page size, margins, orientation, copies, duplex, and color options.
- Check the status of a submitted print job.

The important part: **the printer stays local and is never exposed to the internet.** Cloudflare only provides the secure public connection to your local MCP endpoint; the MCP server renders and submits the job on your machine.

## How It Works

```text
                          Cloudflare Tunnel
                         (outbound connection)
                                |
Any MCP client  ------------>  MCP server  ------------>  CUPS  ------------>  Local printer
                                |                         |
                         Markdown -> PDF            USB or IPP
```

The Docker Compose stack runs three services:

- `mcp` is the MCP server. It renders Markdown and exposes the tools.
- `cups` manages the local printer queue and submits print jobs.
- `cloudflared` is optional. It publishes `mcp` through a Cloudflare named tunnel without opening an inbound port.

## What You Need

- A Linux machine on the same network as the printer.
- Docker Engine and the Docker Compose plugin.
- A network printer that supports IPP Everywhere, or a USB printer.
- For remote agents: a Cloudflare account, a domain on Cloudflare, and a named tunnel.

Docker Desktop is not supported. USB passthrough and host networking differ from the Linux setup this project expects.

## Quick Start

### 1. Configure the server

```bash
git clone <your-repo-url> print-mcp
cd print-mcp
cp .env.example .env
```

Generate secrets and put them in `.env`:

```bash
openssl rand -hex 32  # MCP_BEARER_TOKEN
openssl rand -hex 24  # CUPS_ADMIN_PASSWORD
```

At minimum, set these values:

```dotenv
MCP_BEARER_TOKEN=your-long-random-token
CUPS_ADMIN_PASSWORD=your-long-random-password
```

### 2. Add the local printer

For a modern network printer, add its IP address to `.env`:

```dotenv
CUPS_PRINTER_IP=192.168.1.50
CUPS_PRINTER_NAME=office-printer
```

When the stack starts, CUPS creates an IPP Everywhere queue at `ipp://192.168.1.50/ipp/print`, enables it, and makes it the default printer.

If you do not want automatic setup, leave `CUPS_PRINTER_IP` empty and add a queue manually:

```bash
docker compose exec cups lpadmin \
  -p office-printer \
  -E \
  -v ipp://192.168.1.50/ipp/print \
  -m everywhere
docker compose exec cups lpadmin -d office-printer
```

For a USB printer, use the USB Compose overlay instead:

```bash
docker compose -f compose.yaml -f compose.usb.yaml up -d --build
```

### 3. Start and test locally

```bash
docker compose up -d --build
curl -fsS http://127.0.0.1:8000/healthz
```

The local endpoints are:

- MCP: `http://127.0.0.1:8000/mcp`
- CUPS admin: `http://127.0.0.1:631/admin`

Send a local test print:

```bash
echo 'Hello from print-mcp.' | docker compose exec -T mcp \
  python /app/cli/print_file.py -
```

At this point the agent-facing server is running locally and can print to your local printer. You can stop here if your MCP client runs on the same machine.

## Connect A Remote Agent

To let an MCP client connect from anywhere, put the local MCP endpoint behind a Cloudflare Tunnel.

### 1. Create the Cloudflare route

In Cloudflare Zero Trust:

1. Create a named tunnel.
2. Add a public hostname, for example `print.example.com`.
3. Set its service URL to exactly `http://mcp:8000`.
4. Copy the tunnel token into `.env`.

Then add the same public hostname to the MCP host allow-list:

```dotenv
CLOUDFLARE_TUNNEL_TOKEN=eyJhIjoi...
MCP_ALLOWED_HOSTS=print.example.com
```

The hostname must match exactly. If it does not, the tunnel can be healthy while the MCP server rejects requests with HTTP 421 `Invalid Host header`.

### 2. Start the tunnel

```bash
docker compose --profile tunnel up -d --build
```

Your MCP endpoint is now:

```text
https://print.example.com/mcp
```

The tunnel makes an outbound connection from your machine to Cloudflare. You do not need to expose port 8000 or open an inbound firewall port.

### 3. Add it to your MCP client

Configure your MCP-compatible agent or client with the public URL and the same bearer token from `.env`:

```text
URL:   https://print.example.com/mcp
Token: MCP_BEARER_TOKEN
```

The standard authentication header is:

```http
Authorization: Bearer YOUR_MCP_BEARER_TOKEN
```

For older MCP agents that cannot set an authorization header, use the same token as
the final path segment instead:

```text
https://print.example.com/mcp/YOUR_MCP_BEARER_TOKEN
```

The server treats this URL as an authenticated alias of `/mcp`. Path tokens can be
recorded in proxy, tunnel, browser, or server logs, so prefer the header form when
the client supports it.

The exact configuration shape depends on the MCP client. Look for its remote HTTP, Streamable HTTP, or custom MCP server settings.

Now your agent can print.

## MCP Tools

The server exposes three tools:

### `list_printers`

Lists configured printers and their current capabilities.

### `print_markdown`

Renders Markdown to PDF and submits it to CUPS. It supports:

- `title`
- `printer`
- `page_size`: `letter`, `legal`, or `a4`
- `orientation`: `portrait` or `landscape`
- `margins`
- `copies`: 1 through 10
- `sides`: one-sided, two-sided long-edge, or two-sided short-edge
- `color_mode`: auto, color, or monochrome

The default is letter paper, portrait orientation, and two-sided long-edge printing.

### `get_job_status`

Returns the current state and timestamps for a CUPS print job.

Raw HTML is disabled. Markdown images may use public HTTP/HTTPS URLs or data URIs. Private, loopback, link-local, multicast, and reserved destinations are blocked, including after redirects.

## Local CLI

The same image includes a CLI for printing without an MCP client:

```bash
cat notes.md | docker compose exec -T mcp python /app/cli/print_file.py -

docker compose exec -T mcp python /app/cli/print_file.py notes.md \
  --page-size a4 \
  --orientation portrait \
  --margins-mm 12 \
  --copies 2 \
  --sides two-sided-long-edge \
  --color mono
```

There is also a host-friendly wrapper for files outside the container:

```bash
./bin/print-md.sh --page-size a4 ./docs/report.md
```

## Configuration

Copy `.env.example` to `.env` for the complete list. The settings most people need are:

| Variable | Purpose |
| --- | --- |
| `MCP_BEARER_TOKEN` | Token required by MCP clients |
| `CUPS_ADMIN_PASSWORD` | Password for CUPS administration |
| `CUPS_PRINTER_IP` | IP address for automatic IPP queue setup |
| `CUPS_PRINTER_NAME` | Name of the automatic CUPS queue |
| `DEFAULT_PRINTER` | Queue used when a tool call omits `printer` |
| `CLOUDFLARE_TUNNEL_TOKEN` | Required for the `tunnel` Compose profile |
| `MCP_ALLOWED_HOSTS` | Public hostname accepted by the MCP server |

The MCP server and CUPS are bound to localhost by default. Keep them that way when using Cloudflare Tunnel. The tunnel container reaches MCP over the private Compose network.

## Troubleshooting

Check service state and logs:

```bash
docker compose ps
docker compose logs cups mcp cloudflared
```

Check the two health endpoints:

```bash
curl http://127.0.0.1:8000/healthz
curl http://127.0.0.1:8000/readyz
```

`/healthz` confirms that the MCP process is running. `/readyz` is healthy only after CUPS has at least one configured printer.

Common issues:

- **HTTP 421 through Cloudflare:** add the exact public hostname to `MCP_ALLOWED_HOSTS`, then recreate the `mcp` service with `docker compose up -d mcp`.
- **Tunnel is running but the endpoint does not respond:** verify the Cloudflare public hostname points to `http://mcp:8000` and inspect `docker compose logs cloudflared`.
- **Printer is not found:** use the printer's explicit IPP URI. Discovery does not reliably cross Docker or Tailscale networks.
- **CUPS keeps crashing with `cupsdDoSelect() failed - Bad address!`:** rebuild the image so the CUPS entrypoint applies the file-descriptor limit workaround.

## Development

```bash
uv sync --extra dev
uv run ruff check .
uv run pytest
docker compose config
```
