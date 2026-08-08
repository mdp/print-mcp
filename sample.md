# print-mcp Phase 1 — Smoke Test

This document verifies the markdown-to-print pipeline end to end.

## Why this exists

Phase 1 wires up the local Brother HL-L2350DW over CUPS in Docker and prints a
rendered Markdown document from the CLI — no MCP endpoint yet.

## What gets tested

- Markdown is rendered to a styled PDF (WeasyPrint) with page numbers.
- The PDF is submitted to the `brother-hl2350dw` queue over IPP Everywhere.
- CUPS hands the job to the printer on the LAN.

## Formatting coverage

Bold, *italic*, ~~strikethrough~~, `inline code`, and a code block:

```python
def hello():
    return "phase 1 works"
```

A table:

| Component | Status |
|-----------|--------|
| CUPS in Docker | ready |
| Brother HL-L2350DW | ready |
| WeasyPrint render | ready |
| CLI submit | ready |

A task list:

- [x] Discover printer
- [x] Configure CUPS
- [ ] Ship the MCP endpoint (phase 2)

> If you are reading this, printing worked.