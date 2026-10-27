# TraceFix — 2-Minute Product Walkthrough Script

**Title:** TraceFix: Graph-Native Code Investigation & Verified Repair  
**Duration:** Exactly 120 Seconds (2:00)  
**Tone:** Technical, precise, honest, developer-focused.  

---

### [0:00 – 0:20] Hook: Context Inefficiency in AI Coding

**Visual:**
- Camera opens on the TraceFix 3-panel workspace on the warm cream canvas (`#f3efe6`) at 1600 × 1000 resolution.
- Three floating white cards: **Investigation**, **Dependency Graph**, and **Findings Summary**.

**Narrator:**
> "When coding agents investigate a bug in a multi-thousand-file repository, they usually dump raw files into context or rely on blind keyword search. The result is context bloat, wasted tokens, and hallucinated edits.
>
> TraceFix solves this by grounding code investigation in a repository AST property graph, assembling only the high-signal structural evidence within a strict token budget."

---

### [0:20 – 0:50] Panel 1 & Panel 2: Graph-Native Investigation

**Visual:**
- Cursor selects the active demo repository `github.com/psf/requests` (revision `84773555`).
- Cursor clicks the `requests-1142` preset button. The real bug statement populates the text area.
- Cursor leaves the **"Deep Trace" mode** toggle ON and slides Context Budget to `4,000 tokens`.
- Cursor clicks the dark navy **"Investigate Bug"** button.
- Panel 2 (Dependency Graph) animates into view:
  - Deep navy card in center: `Session.send (Primary Evidence)`.
  - Blue, gray, and red rounded pill nodes connected by directed relation arrows (`calls`, `imports`, `reads`).
  - Cursor clicks a node; the bottom status line displays `requests/sessions.py > Session.send (Line 185)`.
  - Subtitle displays: `Graph Source: AST + Runtime Trace (Disk Snapshot BFS)`.

**Narrator:**
> "In Panel 1, we select our packaged `requests` repository and choose the real issue `requests-1142`.
>
> With a single click, TraceFix traverses caller, callee, and import relationships.
>
> In Panel 2, our dependency graph renders the structural neighborhood. The deep navy card marks our primary evidence function, while connected functions and imports appear in soft blue and slate. Because FalkorDB is offline in this demo, TraceFix truthfully falls back to a verified in-memory disk snapshot."

---

### [0:50 – 1:20] Panel 3: Grounded Evidence & Token Budgeting

**Visual:**
- Camera pans smoothly to Panel 3 (Findings Summary).
- Section 1 displays ranked items:
  - `1  sessions.py > Session.send (94% confidence, Line 185 · Evidence)`
  - `2  models.py > PreparedRequest.prepare_content_length (81% confidence, Line 412)`
- Section 2 shows the **Context Budget Meter**:
  - `3.9k / 4.0k tokens used` with progress bar.
- Section 3 shows **Proposed Fix**:
  - Unified diff preview with red and green code changes.
- Section 4 shows **Verification**:
  - Displays truthful status pill: `Unavailable (No LLM Key)` or `Tests Failed / Passed`.
  - Shell log box shows `mcp verify-task` command logs.

**Narrator:**
> "In Panel 3, we see the assembled findings.
>
> TraceFix extracted grounded functions with exact line boundaries. Notice our Context Budget Meter: out of 4,000 allowed tokens, TraceFix packed 3,990 tokens using our CharDiv4 heuristic counter, discarding 8 lower-relevance candidates.
>
> And in our verification section, TraceFix stays completely honest: because no external LLM key is configured on this public demo, automated repair is labeled UNAVAILABLE rather than faking a synthetic test pass."

---

### [1:20 – 1:45] MCP Server Integration for Coding Agents

**Visual:**
- Cursor clicks the green `mcp-server: connected` pill badge in the top-right of Panel 1.
- The **MCP Setup Modal** opens, showing configuration JSON for Claude Desktop and Cursor IDE.
- Quick cutaway to terminal: `tracefix-mcp` running over standard I/O, responding to `build_investigation_context` tool calls.

**Narrator:**
> "TraceFix is also an official Model Context Protocol server.
>
> By running `tracefix-mcp` locally over standard input/output, compatible coding agents like Claude Desktop or Cursor can invoke `find_relevant_code`, `trace_dependencies`, and `build_investigation_context` directly.
>
> Your agent gets repository intelligence natively, with zero copy-pasting into chat."

---

### [1:45 – 2:00] Summary & Truth in Engineering

**Visual:**
- Modal closes, revealing the full 3-card workspace.
- Clear title text: `TraceFix: Verified, Grounded, Context-Budgeted Repository Intelligence`.
- GitHub link displayed.

**Narrator:**
> "TraceFix delivers honest, grounded developer tooling: real AST property graphs, strict token budgets, truthful offline fallbacks, and native MCP support.
>
> Run TraceFix locally today or inspect the open-source implementation on GitHub. Thank you."
