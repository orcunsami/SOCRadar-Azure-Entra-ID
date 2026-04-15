# Entra ID Integration — Diagrams

Three diagrams describing the system and progress. Each `.mmd` is Mermaid source.

## How to view in draw.io (recommended)

1. Open https://app.diagrams.net (or desktop app)
2. Start a new blank diagram
3. Menu: **Arrange → Insert → Advanced → Mermaid**
4. Paste the contents of one `.mmd` file
5. Click **Insert** — draw.io auto-lays out the diagram
6. Edit/move boxes freely after insertion
7. Repeat for each diagram on a new page (bottom tabs)

## How to view in VS Code

Install the **Mermaid Preview** extension, open any `.mmd` file, cmd+shift+v.

## How to view on GitHub

GitHub renders Mermaid natively in `.md` files. To view on GitHub, inline the
Mermaid block inside a markdown file between triple-backtick fences with
`mermaid` as the language.

## Diagrams

| File | Description |
|------|-------------|
| `01-architecture.mmd` | Component architecture — which system talks to which, with full endpoint URLs and permission hints. |
| `02-runtime-sequence.mmd` | One timer tick end-to-end — shows the full flow from SOCRadar fetch through Entra actions to LAW/Sentinel write. Includes the new Force MFA Re-registration step. |
| `03-progress-state.mmd` | Current project state — what's done (4 commits on master), what's blocked externally (admin tasks), what's pending user decision (MSSP). |

## Quick terminal preview (without rendering)

If you just want the structure:

```bash
head -5 *.mmd    # diagram titles + first few lines
```
