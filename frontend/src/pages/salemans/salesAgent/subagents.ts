/** The sub-agents the assistant hands work to (backend/sales-agent-engine app/engine/delegation.py). */
const TITLES: Record<string, string> = {
  research: 'research agent',
  outreach: 'outreach agent',
  quote: 'quote agent',
};

/** The sub-agent's name for the rep, or null when the assistant itself did the work. */
export function subagentTitle(agent: string | null | undefined): string | null {
  return agent ? (TITLES[agent] ?? null) : null;
}
