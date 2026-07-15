---
name: gws-calendar-agenda
description: "Google Calendar: Show upcoming events across all calendars."
metadata:
  version: 0.22.4
  openclaw:
    category: "productivity"
    requires:
      bins:
        - gwsx
    cliHelp: "gwsx <account> calendar +agenda --help"
---

# calendar +agenda

> **PREREQUISITE:** Read `../gws-shared/SKILL.md` for account selection, auth, global flags, and security rules.

Show upcoming events across all calendars

## Usage

```bash
gwsx <account> calendar +agenda
```

## Flags

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--today` | — | — | Show today's events |
| `--tomorrow` | — | — | Show tomorrow's events |
| `--week` | — | — | Show this week's events |
| `--days` | — | — | Number of days ahead to show |
| `--calendar` | — | — | Filter to specific calendar name or ID |
| `--timezone` | — | — | IANA timezone override (e.g. America/Denver). Defaults to Google account timezone. |

## Examples

```bash
gwsx <account> calendar +agenda
gwsx <account> calendar +agenda --today
gwsx <account> calendar +agenda --week --format table
gwsx <account> calendar +agenda --days 3 --calendar 'Work'
gwsx <account> calendar +agenda --today --timezone America/New_York
```

## Tips

- Read-only — never modifies events.
- Queries all calendars by default; use --calendar to filter.
- Uses your Google account timezone by default; override with --timezone.

## See Also

- [gws-shared](../gws-shared/SKILL.md) — Global flags and auth
- [gws-calendar](../gws-calendar/SKILL.md) — All manage calendars and events commands
