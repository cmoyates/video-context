# Agent guidance

Codex is the primary agent. Skills are maintained in `.agents/skills/`;
`.claude/skills/` provides compatibility links to the same Matt Pocock skills.

## Agent skills

### Python anti-slop

For Python anti-slop reviews, cleanup, or lint-policy installation and updates,
read `.agents/skills/python-anti-slop/SKILL.md`. Its references distinguish
mechanical checks from judgments that need code and caller evidence.

### Issue tracker

Use GitHub Issues in `cmoyates/video-context`. Before creating, updating, or
organizing issues or specs, read `docs/agents/issue-tracker.md`.

### Triage labels

Use the five default triage roles. Before applying triage labels, read
`docs/agents/triage-labels.md`.

### Domain docs

Use one root glossary and `docs/adr/`. Before domain exploration or documenting
terms and decisions, read `docs/agents/domain.md`.
