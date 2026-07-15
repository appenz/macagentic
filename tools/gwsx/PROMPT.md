### `gwsx` command for Google Workspace apps with explicit accounts.
- Always choose a configured account alias as the first argument.
- Add an account interactively: `gwsx account add <alias>`
- Delete an account and its local credentials: `gwsx account delete <alias>`
- List configured accounts: `gwsx account list`
- Pass Google Workspace CLI arguments through unchanged: `gwsx <alias> <gws arguments...>`
- Example: `gwsx private drive files list --params '{"pageSize": 5}'`
- Re-authenticate an account: `gwsx <alias> auth login --scopes drive,gmail`
