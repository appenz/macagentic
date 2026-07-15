---
name: gws-gmail-triage
description: "Gmail: Show unread inbox summary (sender, subject, date)."
metadata:
  version: 0.22.4
  openclaw:
    category: "productivity"
    requires:
      bins:
        - gwsx
    cliHelp: "gwsx <account> gmail +triage --help"
---

# gmail +triage

> **PREREQUISITE:** Read `../gws-shared/SKILL.md` for account selection, auth, global flags, and security rules.

Show unread inbox summary (sender, subject, date)

## Usage

```bash
gwsx <account> gmail +triage
```

## Flags

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--max` | — | 20 | Maximum messages to show (default: 20) |
| `--query` | — | — | Gmail search query (default: is:unread) |
| `--labels` | — | — | Include label names in output |

## Examples

```bash
gwsx <account> gmail +triage
gwsx <account> gmail +triage --max 5 --query 'from:boss'
gwsx <account> gmail +triage --format json | jq '.[].subject'
gwsx <account> gmail +triage --labels
```

## Tips

- Read-only — never modifies your mailbox.
- Defaults to table output format.

## See Also

- [gws-shared](../gws-shared/SKILL.md) — Global flags and auth
- [gws-gmail](../gws-gmail/SKILL.md) — All send, read, and manage email commands
