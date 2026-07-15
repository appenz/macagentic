# Skills

Skills live at `~/.agents/skills/<skillname>/SKILL.md` or under a tool at
`tools/<toolname>/skills/<skillname>/SKILL.md`. The directory name is the skill
name. Each file has YAML frontmatter with a `description` and optional
`disable-model-invocation` and `user-invocable` booleans, followed by its
instructions. Skill names must be unique across user and tool directories;
startup fails with both paths when a duplicate is found.

At startup, macAgentic reads the skills once and replaces `{{SKILLS}}` in the
system prompt with a generated list. Skills with
`disable-model-invocation: true` are omitted. The agent loads a listed skill by
reading the exact `SKILL.md` path shown in that list.

A whitespace-delimited `/skillname` in user input expands to that skill's
instructions without its frontmatter. Expansion applies only to skills where
`user-invocable` is true, which is the default. Unknown slash commands remain
unchanged.
