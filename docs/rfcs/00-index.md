# RFCs

Design records for Life Copilot. The rules an agent follows live in `AGENTS.md` and `prompts/`; an RFC records why a version changed them, what the change had to achieve, and how it was checked.

| RFC | Status | What it changed |
|---|---|---|
| [[life-copilot-v4.3-rfc]] | implemented 2026-06-05 | From a Quant roadmap executor to a life-wide system: seeds, index-guided routing, the Active Board, schedules as projections |
| [[life-copilot-v4.4-rfc]] | implemented 2026-07-25 | One merged Chat capture, an explicit bedtime close, constrained rule evolution |
| [[life-copilot-v4.5-rfc]] | implemented 2026-09-22, except the chat-mode promotion | Read budget, people pages, closing-greeting rules moved out of memory |
| [[life-copilot-v4.6-rfc]] | in progress | Book pages: a people page for a book, plus a linked reading trail |
| [[life-copilot-v4.7-rfc]] | in progress: code, pilot page and rules landed 2026-10-04, observing until 2026-10-11 | A page and its trail: the page holds what changes and fits in one read, a dated append-only trail holds what accumulates |
| [[life-copilot-v4.8-rfc]] | in progress: code and rules landed 2026-10-09, observing until 2026-10-16 | A day timeline: every session of the day on one time axis, rebuilt from the traces and read before them |
| [[life-copilot-v4.9-rfc]] | in progress: code, entry file and sync job landed 2026-10-10, observing until 2026-10-17 | Kai becomes an entrance with no rules or memory of its own; traces are refreshed during the day and the mirror is pushed within a minute of a change |

## Conventions

- Write an RFC only for a structural change: a layer added or removed, a change to L2, or to the file map. A smaller change is explained in its commit message.
- An RFC may be updated while its version is being implemented. Once its status says implemented it is frozen, and a later revision goes into the next RFC.
- The current RFC is the one `AGENTS.md` and `README.md` link to.
