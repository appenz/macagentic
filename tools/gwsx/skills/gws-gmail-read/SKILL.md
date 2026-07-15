---
name: gws-gmail-read
description: "Gmail: Read a message and extract its body or headers."
metadata:
  version: 0.22.4
  openclaw:
    category: "productivity"
    requires:
      bins:
        - gwsx
    cliHelp: "gwsx <account> gmail +read --help"
---

# gmail +read

> **PREREQUISITE:** Read `../gws-shared/SKILL.md` for account selection, auth, global flags, and security rules.

Read a message and extract its body or headers

## Usage

```bash
gwsx <account> gmail +read --id <ID>
```

## Flags

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--id` | ✓ | — | The Gmail message ID to read |
| `--headers` | — | — | Include headers (From, To, Subject, Date) in the output |
| `--format` | — | text | Output format (text, json) |
| `--html` | — | — | Return HTML body instead of plain text |
| `--dry-run` | — | — | Show the request that would be sent without executing it |

## Examples

```bash
gwsx <account> gmail +read --id 18f1a2b3c4d
gwsx <account> gmail +read --id 18f1a2b3c4d --headers
gwsx <account> gmail +read --id 18f1a2b3c4d --format json | jq '.body'
```

## Tips

- Converts HTML-only messages to plain text automatically.
- Handles multipart/alternative and base64 decoding.

## See Also

- [gws-shared](../gws-shared/SKILL.md) — Global flags and auth
- [gws-gmail](../gws-gmail/SKILL.md) — All send, read, and manage email commands
