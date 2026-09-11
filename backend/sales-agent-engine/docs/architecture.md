# Full Sales AI Agnet Architecture - Eraser.io code

```
direction down

// ============================================================
// RoleSync — Sales Agent Engine (AI Sales OS) — COMPLETE
// Reactive engine + Autonomous goal layer (single task AND
// long-running self-waking goals). [NEW] build · [EXISTS] reuse.
// ============================================================

title Sales Agent Engine — Complete (Reactive + Autonomous)

// ---------- 1 · ENTRY (two ways in) ----------
Entry [color: blue] {
  ChatUI [icon: message-circle, color: blue, label: "Chat UI [NEW]\nsingle task: one prompt"]
  GoalUI [icon: target, color: blue, label: "Goal UI [NEW]\nlong goal: 'sell 200 this month'"]
  StreamChannel [icon: activity, color: blue, label: "SSE / WebSocket [NEW]\nlive events out"]
  ApprovalUI [icon: check-circle, color: red, label: "Approval cards [NEW]\napprove / edit / reject · TTL"]
}

// ---------- 2 · GATEWAY ----------
Gateway [color: gray] {
  APIGateway [icon: shield, color: gray, label: "API Gateway [EXISTS]\nJWT · rate limit · resolve tenant"]
}

// ---------- 3 · AUTONOMY LAYER [NEW] (drives the engine over time) ----------
Autonomy Layer [color: purple] {
  GoalManager [icon: target, color: purple, label: "Goal manager [NEW]\ngoal · deadline · progress · strategy\nbudget caps · priority · terminal conditions"]
  Scheduler [icon: clock, color: amber, label: "Scheduler [NEW]\ntime-based wake: follow-ups, pacing"]
  TriggerListener [icon: bell, color: teal, label: "Trigger listener [NEW]\nevent wake: reply · order · stock-out"]
  WakeQueue [icon: list, color: coral, shape: cylinder, label: "Wake queue [NEW]\nidempotent · deduped · rate-controlled\n(trigger-storm safe)"]
  AutonomyPolicy [icon: shield, color: red, label: "Autonomy policy envelope [NEW]\ninside → act alone · outside → human approval"]
}

// ---------- 4 · REACTIVE ENGINE (reused every wake) ----------
Agent Engine [color: purple] {
  "Orchestration Core (LangGraph)" [color: purple] {
    Planner [icon: git-branch, color: purple, label: "Orchestrator / Planner\nONLY coordinator · re-assesses each wake"]
    DurableState [icon: save, color: purple, label: "Durable execution\ncheckpoint · pause · resume"]
    ToolRouter [icon: shuffle, color: purple, label: "Tool router\npick tool · sequence"]
  }
  "Execution Guardrails [NEW]" [color: red] {
    Limits [icon: gauge, color: red, label: "Limits\nsteps · depth · cost per run"]
    CircuitBreaker [icon: alert-octagon, color: red, label: "Circuit breaker\nstop runaway / loops"]
    RetryTimeout [icon: refresh-cw, color: red, label: "Retry + timeout\nper tool call"]
    Saga [icon: rotate-ccw, color: red, label: "Saga / compensation\nundo on failure"]
  }
  "Sub-Agents — scoped" [color: pink] {
    ResearchAgent [icon: search, color: pink, label: "Research agent\nREAD-only scope"]
    OutreachAgent [icon: mail, color: pink, label: "Outreach agent\nSEND scope"]
    QuoteAgent [icon: file-text, color: pink, label: "Quote agent\nCATALOG scope"]
  }
  "Streaming & Control" [color: amber] {
    EventEmitter [icon: radio, color: amber, label: "Event emitter\nstep · token · awaiting"]
    HITLGate [icon: hand, color: red, label: "Human-in-the-loop gate\npause → approve → resume · TTL"]
  }
}

// ---------- 4b · SHARED CONTEXT + MEMORY [NEW] ----------
Context and Memory [color: teal] {
  ContextManager [icon: layers, color: teal, label: "Context manager [NEW]\ncompress · summarize · offload"]
  StateLock [icon: lock, color: teal, label: "State lock + version [NEW]\nno concurrent-write corruption"]
  ConvMemory [icon: message-square, color: teal, label: "Conversation memory"]
  RepMemory [icon: user, color: teal, label: "Rep memory"]
  DealMemory [icon: briefcase, color: teal, label: "Deal / account memory"]
}

// ---------- 5 · MODEL ROUTER ----------
Model Router [color: teal] {
  ModelRouter [icon: shuffle, color: teal, label: "Model router [NEW]\ncomplexity + failover"]
  Gemini [icon: cpu, color: green, label: "Gemini [PRIMARY]\ncomplex reasoning"]
  OpenRouter [icon: cpu, color: blue, label: "OpenRouter [SECONDARY]\nsimple + fallback"]
}

// ---------- 6 · GATED TOOL LAYER ----------
Gated Tool Layer [color: green] {
  ToolGate [icon: lock, color: green, label: "Tool gate [NEW]\nEVERY call: tenant + ACL + agent-scope + audit"]
  PermissionCheck [icon: key, color: green, label: "Permission check\nper-agent scope"]
  AuditLogger [icon: file-text, color: coral, label: "Audit logger\nevery action"]
}

// ---------- 7 · TOOLS ----------
Communication Tools [color: gray] {
  GmailTool [icon: mail, color: gray, label: "Gmail [EXISTS]\nread · send · reply"]
  CalendarTool [icon: calendar, color: gray, label: "Calendar [EXISTS]"]
  SlackTool [icon: message-square, color: gray, label: "Slack [EXISTS]"]
  NotionTool [icon: book, color: gray, label: "Notion [EXISTS]"]
}
Knowledge Tools [color: blue] {
  RetrievalTool [icon: database, color: blue, label: "Knowledge base [EXISTS]"]
  CatalogTool [icon: package, color: blue, label: "Catalog [NEW]\nproducts · variants · stock"]
  DealTool [icon: briefcase, color: blue, label: "Deal / CRM [NEW]"]
}
Action Tools [color: amber] {
  DocGenTool [icon: file, color: amber, label: "Doc generator [NEW]"]
  DriveTool [icon: hard-drive, color: amber, label: "Drive [EXISTS]"]
  QuoteTool [icon: dollar-sign, color: amber, label: "Quote / proposal [NEW]"]
}
Intelligence Tools [color: coral] {
  WebSearch [icon: globe, color: coral, label: "Web search [NEW]"]
  ProspectResearch [icon: users, color: coral, label: "Prospect research [NEW]"]
}

// ---------- 8 · CROSS-CUTTING [NEW] ----------
Cross Cutting [color: amber] {
  Tracing [icon: git-commit, color: amber, label: "Observability / tracing [NEW]\nfull execution trace · replay"]
  TenantBudget [icon: gauge, color: coral, label: "Per-tenant budgets [NEW]\nrate · cost · concurrency"]
}

// ---------- 9 · DATA ----------
Stores [color: purple] {
  GoalDB [icon: target, color: purple, shape: cylinder, label: "Goal DB [NEW]\ngoals · progress · schedules"]
  AgentStateDB [icon: database, color: purple, shape: cylinder, label: "Agent state [NEW]\ncheckpoints · saga log"]
  MemoryStore [icon: database, color: teal, shape: cylinder, label: "Memory store [NEW]\nversioned"]
  AuditDB [icon: shield, color: coral, shape: cylinder, label: "Audit + trace DB [NEW]"]
  ExistingData [icon: database, color: gray, shape: cylinder, label: "Existing data [EXISTS]\nPostgres · Mongo · pgvector"]
}

// ================= FLOWS =================

// single task path
ChatUI > APIGateway: one prompt
// long goal path
GoalUI > APIGateway: set goal
APIGateway > TenantBudget: check budget
TenantBudget > GoalManager: goal (long)
TenantBudget > Planner: task (single)

// autonomy loop: goal → wake sources → queue → policy → engine
GoalManager > Scheduler: register time wakes
GoalManager > TriggerListener: subscribe to events
TriggerListener > ExistingData: watch Composio events
Scheduler > WakeQueue: time wake
TriggerListener > WakeQueue: event wake
WakeQueue > AutonomyPolicy: next wake (deduped)
AutonomyPolicy > Planner: within envelope → run
AutonomyPolicy > HITLGate: outside envelope → human first
GoalManager > GoalDB: persist goal + progress

// each wake runs the reactive engine (re-assess against goal)
Planner > GoalManager: read goal + progress
Planner > Limits: check each step
Limits > CircuitBreaker: threshold → halt
Planner > DurableState: checkpoint
DurableState > AgentStateDB: persist
Planner > ToolRouter: sub-goals
ToolRouter > ResearchAgent: delegate
ToolRouter > OutreachAgent: delegate
ToolRouter > QuoteAgent: delegate
ResearchAgent > Planner: result only
OutreachAgent > Planner: result only
QuoteAgent > Planner: result only

// shared context only through manager
Planner > ContextManager: read/write
ResearchAgent > ContextManager: read/write
OutreachAgent > ContextManager: read/write
QuoteAgent > ContextManager: read/write
ContextManager > StateLock: guard writes
ContextManager > ConvMemory: manage
ContextManager > RepMemory: manage
ContextManager > DealMemory: manage
ConvMemory > MemoryStore: persist
RepMemory > MemoryStore: persist
DealMemory > MemoryStore: persist

// reasoning
Planner > ModelRouter: needs a brain
ResearchAgent > ModelRouter: needs a brain
OutreachAgent > ModelRouter: needs a brain
QuoteAgent > ModelRouter: needs a brain
ModelRouter > Gemini: complex
ModelRouter > OpenRouter: simple / failover

// events + tracing + approval
Planner > EventEmitter: progress
EventEmitter > StreamChannel: push
StreamChannel > ChatUI: live events
HITLGate > ApprovalUI: awaiting approval
ApprovalUI > HITLGate: approve / edit / reject
HITLGate > Saga: timeout → compensate
Planner > Tracing: trace decisions
Tracing > AuditDB: store trace

// all tool calls gated + guarded
ToolRouter > RetryTimeout: wrap call
RetryTimeout > ToolGate: guarded call
OutreachAgent > ToolGate: tool call
ResearchAgent > ToolGate: tool call
QuoteAgent > ToolGate: tool call
ToolGate > PermissionCheck: tenant + agent scope
ToolGate > AuditLogger: log
AuditLogger > AuditDB: write
ToolGate > HITLGate: writes need approval
ToolGate > Saga: record side-effect

// gate → tools
ToolGate > GmailTool: read/write
ToolGate > CalendarTool: read/write
ToolGate > SlackTool: read/write
ToolGate > NotionTool: read/write
ToolGate > RetrievalTool: query/write
ToolGate > CatalogTool: query/write
ToolGate > DealTool: read/update
ToolGate > DocGenTool: generate
ToolGate > DriveTool: store
ToolGate > QuoteTool: assemble
ToolGate > WebSearch: search
ToolGate > ProspectResearch: research

// progress feedback closes the loop
CatalogTool > GoalManager: units sold → update progress
DealTool > GoalManager: deals closed → update progress

// tools → data
RetrievalTool > ExistingData: vector + docs
CatalogTool > ExistingData: structured
DealTool > ExistingData: structured
DriveTool > RetrievalTool: fallback to KB
```