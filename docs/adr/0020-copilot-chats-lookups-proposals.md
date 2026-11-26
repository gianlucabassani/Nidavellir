# ADR-0020: Copilot chats, read-only lookups and confirmed proposals

- **Status:** Accepted
- **Date:** 2026-11-26
- **Deciders:** Nidavellir operator

## Context

The console co-pilot streams answers from the operator's own connected model,
with the current arena's context injected. It is advise-only:
- it keeps no history beyond the open panel;
- it cannot look anything up;
- it cannot help the operator act.

The operator asked for a copilot panel that keeps chat history, reads the
console's data to answer, and can propose actions.

A model must never change the platform by itself. Everything it reads can carry
text written by a target or by an agent under test. Nidavellir's connections are
bring-your-own across many providers (OpenAI-compatible, Anthropic, local), and
not all of them support native tool calling.

## Decision

**Stored chats.**
- `copilot_chats` (id, owner, title, created/updated) and `copilot_messages`
  (chat, role, text, data, created) hold each operator's conversations.
- Only the owning operator can read, continue or delete a chat. Agent keys
  cannot reach any copilot route.
- A chat keeps at most 200 messages. Each message is bounded.

**Lookups without tool calling.** Each turn runs in two passes over the
operator's connection.
1. The **plan pass** asks the model for a single JSON object naming up to three
   lookups from a fixed allow-list:
   - `arena_summary(arena_id)`
   - `arena_activity(arena_id)`
   - `findings(arena_id?)`
   - `agents_board()`
   - `search(q)`

   The server validates names and arguments (shape, length, existing arena ids)
   and drops anything else.
2. The server runs the lookups with operator permissions. Each result is
   bounded and redacted, then wrapped in a `<data source=… untrusted>` block.
3. The **answer pass** streams the reply.

The system prompt states that data blocks are information, never instructions.
Each lookup is stored and shown as a "Looked up" chip.

**Proposals, confirmed by the operator.**
- The answer may end with one fenced `nv-proposal` JSON object from a fixed
  allow-list:
  - `extend_arena(arena_id, seconds ∈ {1800, 3600, 7200})`
  - `stop_research(arena_id)`
  - `resume_research(arena_id)`
- The server parses and validates it, strips it from the visible text, and
  stores it as a pending proposal. Anything unknown or malformed is dropped and
  noted.
- The panel renders the proposal as a card. **Apply** calls the same console
  endpoint the console's own button calls, from the operator's browser session,
  with CSRF. The proposal is then marked applied or failed. **Deny** marks it
  denied.
- The copilot routes never execute a proposal themselves.

**Page context is opt-in.** The current page is sent only while the operator
keeps its chip on, and the chip shows exactly what is sent.

## Alternatives considered

- **Native tool calling per provider:** this needs per-provider code and fails
  on connections without tools. The plan pass works with any chat model.
- **Let the server execute proposals after the model asks:** this moves the
  trust boundary to model output. Apply must be the operator's own request.
- **Keep chats only in browser storage:** history would be lost across
  browsers. ADR-0017 also keeps research material out of browser storage.

## Consequences

- One extra model call per turn (the plan pass). It is skipped when the plan
  returns no lookups quickly.
- Text written by a target can still try to steer the plan or answer passes.
  Lookups are read-only and bounded, proposals come from an allow-list, and
  every action needs the operator's click, so steering can at worst mislead,
  never act.
- Adding a lookup or proposal kind means changing the allow-list and its
  validator together, with tests.
- Chats are owned by the orchestrator principal that calls the API. The console
  reaches the orchestrator as one principal, as it already does for model
  connections. Operators who share one console therefore share its chats, the
  same way they share its model connection.
- The ``/agent/chat`` advise-only route stays for existing callers. The console
  panel uses the copilot routes.
