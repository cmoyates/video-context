# Issue tracker: GitHub

Issues and specs live in `cmoyates/video-context`. Use `gh` from this checkout,
or specify `--repo cmoyates/video-context` when working elsewhere.

## Issue operations

- Read: `gh issue view <number> --json number,title,body,labels,comments`.
- List: `gh issue list --state open --json number,title,body,labels`.
- Create: `gh issue create --title "..." --body-file <file>`.
- Comment: `gh issue comment <number> --body-file <file>`.
- Label: `gh issue edit <number> --add-label "..." --remove-label "..."`.
- Close: `gh issue close <number>` after the acceptance criteria are met.

Use a UTF-8 file for multiline bodies. Publishing a spec means creating an issue;
fetching a ticket means reading its issue and relevant comments.

## Relationships and wayfinding

Use GitHub sub-issues for parent/child relationships and native issue dependencies
for blockers. Before adding a dependency, check the existing graph for cycles.
The REST endpoints expect issue database IDs, not issue numbers or node IDs.
If those features are unavailable, use `Part of #<parent>` and
`Blocked by: #<number>` lines in issue bodies, plus a task list in the parent.

For wayfinding, the map is an issue labelled `wayfinder:map`; child tickets use
`wayfinder:research`, `wayfinder:prototype`, `wayfinder:grilling`, or `wayfinder:task`.
Create these labels when that workflow is first used. A ticket is available when
it is open, unassigned, and all blockers are closed. Claim it by assigning the
current user. Record the result on the ticket and update the map when resolved.

## Pull requests as a triage surface

**PRs as a request surface: no.**
