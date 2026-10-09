# Domain docs

This project uses a single domain context: `GLOSSARY.md` at the repository root
and architecture decisions in `docs/adr/`.

Before exploring an area, read the glossary if present and any ADRs relevant to
that area. If these documents do not exist yet, continue silently. The
`domain-modeling` skill creates them as terms and decisions are resolved.

Use glossary terms consistently in code, tests, issues, and explanations. When a
needed concept is absent, raise it during domain modeling rather than silently
introducing a competing term. Surface conflicts with an existing ADR explicitly.
