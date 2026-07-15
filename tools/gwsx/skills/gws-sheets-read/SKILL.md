---
name: gws-sheets-read
description: "Google Sheets: Read values from a spreadsheet."
metadata:
  version: 0.22.4
  openclaw:
    category: "productivity"
    requires:
      bins:
        - gwsx
    cliHelp: "gwsx <account> sheets +read --help"
---

# sheets +read

> **PREREQUISITE:** Read `../gws-shared/SKILL.md` for account selection, auth, global flags, and security rules.

Read values from a spreadsheet

## Usage

```bash
gwsx <account> sheets +read --spreadsheet <ID> --range <RANGE>
```

## Flags

| Flag | Required | Default | Description |
|------|----------|---------|-------------|
| `--spreadsheet` | ✓ | — | Spreadsheet ID |
| `--range` | ✓ | — | Range to read (e.g. 'Sheet1!A1:B2') |

## Examples

```bash
gwsx <account> sheets +read --spreadsheet ID --range "Sheet1!A1:D10"
gwsx <account> sheets +read --spreadsheet ID --range Sheet1
```

## Tips

- Read-only — never modifies the spreadsheet.
- For advanced options, use the raw values.get API.

## See Also

- [gws-shared](../gws-shared/SKILL.md) — Global flags and auth
- [gws-sheets](../gws-sheets/SKILL.md) — All read and write spreadsheets commands
