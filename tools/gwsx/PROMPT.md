`gwsx` — Google Workspace. First argument is always a configured account alias.
- Accounts: `gwsx account add <alias>` · `gwsx account delete <alias>` · `gwsx account list`
- Run: `gwsx <alias> <gws arguments...>`
- Re-auth: `gwsx <alias> auth login --scopes drive,gmail`
- Example: `gwsx private drive files list --params '{"pageSize": 5}'`
