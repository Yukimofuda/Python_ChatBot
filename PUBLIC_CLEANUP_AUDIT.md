# Public cleanup audit

This package was generated from the latest uploaded private project snapshot.

## Preserved

- Generic NoneBot2/OneBot V11 runtime.
- Admin Web, utility, fun, sign-in, points, and Bilibili plugins.
- Generic memory command plugins.
- `src/chatbot/bot_brain/` memory-related modules: social cognition store, memory CRUD, governance, alias index, retrieval boundary helpers, migration/shadow helpers, admin memory facade, identity/alias abstractions, and output guard.

## Removed or neutralized

- Private `.git`, `.env`, `.venv`, `data`, logs, backups, caches, PDFs, private docs, memory-bank, and local reports.
- Private persona files and top-level character prompts.
- Persona/roleplay plugins: ambient reply, dream diary, meme memory, memory fortune, persona live, lifecycle.
- Persona/LLM-life modules under the old brain package: generator, planner, persona engine, prompt files, reflection/life/self-state modules.
- Hard-coded private owner/private persona identifiers and local paths.
- Old `src/chatbot/private_brain` import path, replaced by `src/chatbot/bot_brain`.

## Remaining public memory boundary

The retained memory system stores and retrieves generic profile memories keyed by platform account IDs. It includes write gates, CRUD/audit helpers, alias resolution, soft deletion/governance, and public output guards. It is not a private persona system.
