# RFCs

Design records for Life Copilot. The rules an agent follows live in `AGENTS.md` and `prompts/`; an RFC records why a version changed them, what the change had to achieve, and how it was checked.

| RFC | Status | What it changed |
|---|---|---|
| [[life-copilot-v4.3-rfc]] | implemented 2026-06-05 | From a Quant roadmap executor to a life-wide system: seeds, index-guided routing, the Active Board, schedules as projections |
| [[life-copilot-v4.4-rfc]] | implemented 2026-07-25 | One merged Chat capture, an explicit bedtime close, constrained rule evolution |
| [[life-copilot-v4.5-rfc]] | implemented 2026-09-22, except the chat-mode promotion | Read budget, people pages, closing-greeting rules moved out of memory |

## Conventions

- Write an RFC only for a structural change: a layer added or removed, a change to L2, or to the file map. A smaller change is explained in its commit message.
- An RFC may be updated while its version is being implemented. Once its status says implemented it is frozen, and a later revision goes into the next RFC.
- The current RFC is the one `AGENTS.md` and `README.md` link to.
