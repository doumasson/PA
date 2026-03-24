# AI Company — Multi-Agent Orchestration System

## Vision
A "virtual company" of specialist AI agents that collaborate on any task — from building software to validating business ideas to running personal finances. You give a directive ("build me a GoHighLevel competitor" or "fix my game and bring it to market"), and a team of agents works through it with checks and balances.

## The Agents (Baseline Roles)

Each agent starts as an SME in their field, then adapts to the specific task:

| Agent | Role | Example Contributions |
|-------|------|----------------------|
| **Researcher** | Market research, competitor analysis, customer review mining | "GoHighLevel has 2.3 stars on G2 for reporting — here's what users hate" |
| **Analyst** | Data analysis, viability scoring, financial modeling | "TAM is $4.2B, here's unit economics at 3 price points" |
| **Strategy** | Business planning, roadmap, go-to-market | "Phase 1: CRM + email. Phase 2: funnels. Phase 3: full suite" |
| **Marketing** | Positioning, pricing, messaging, content strategy | "Undercut on price, lead with 'built by AI' angle" |
| **Sales** | Revenue model, customer acquisition, objection handling | "PLG with free tier, enterprise upsell at 50 seats" |
| **Naysayer** | Devil's advocate, risk identification, assumption challenging | "Your churn model assumes 5% monthly but industry avg is 8%" |
| **Dev** | Architecture, implementation, code generation | "Monorepo, Next.js frontend, Python API, PostgreSQL" |
| **UI/UX Engineer** | Design systems, user flows, wireframes, accessibility | "Onboarding wizard reduces time-to-value from 2hrs to 15min" |
| **SQL Admin/Developer** | Database design, query optimization, data modeling | "Star schema for analytics, JSONB for custom fields" |
| **IT Guy** | Infrastructure, deployment, monitoring, scaling | "K8s on AWS, multi-tenant with tenant isolation at DB level" |
| **Cyber Security** | Threat modeling, pen testing, compliance gaps | "SOC2 requires encrypted PII at rest — your schema exposes emails" |
| **Compliance & Training** | Regulatory, legal, documentation, onboarding | "GDPR data deletion flow missing, need DPA template" |

## Interaction Model

**Hybrid checkpoint + live conversation:**
- Agents run in phases (Research → Strategy → Design → Build)
- Review and approve at each phase checkpoint before next starts
- Can intervene anytime and talk to specific agents directly
- Can override decisions, redirect focus, add constraints

## How It Maps to Albus Architecture

### What already exists:
- **Plugin system** — Each agent = a plugin with its own commands, NL handlers, jobs
- **Brain with tiers** — Agents can use Haiku for quick checks, Sonnet for analysis, Opus for deep strategy
- **Conversation memory** — Each agent maintains its own context window
- **System prompt fragments** — Each agent's expertise injected via `system_prompt_fragment()`
- **Self-teaching** — Agents learn from corrections (preference detection already built)
- **Telegram interface** — Already handles NL routing by keyword

### What needs to be built:
1. **Workflow engine** — Defines phase sequences, routes tasks between agents, manages state
2. **Agent isolation** — Each agent gets its own conversation context, memory, and role prompt (not shared)
3. **Inter-agent messaging** — Agents pass deliverables to each other (Researcher → Analyst → Strategy)
4. **Checkpoint system** — Surfaces phase summaries to user for approval before continuing
5. **Direct addressing** — "Hey Marketing, what about pricing?" routes to specific agent
6. **Shared workspace** — Common artifact store (docs, code, data) all agents can read/write
7. **Naysayer pattern** — Designated contrarian agent that reviews every other agent's output
8. **MCP integration** — Agents can use external tools (browser, shell, APIs) via Model Context Protocol

### Incremental path:
1. **Now:** Keep building Albus with clean plugin interfaces, good separation of concerns
2. **Soon:** Abstract Brain to support multiple isolated conversations (agent contexts)
3. **Next:** Build a simple 2-agent workflow (e.g., Researcher → Analyst) as proof of concept
4. **Then:** Add the workflow engine, checkpoint system, direct addressing
5. **Finally:** Full agent roster with inter-agent messaging and shared workspace

## Example Workflows

### "Build me a GoHighLevel competitor"
```
User → Researcher (analyze GoHighLevel, competitors, reviews, gaps)
     → Analyst (market sizing, viability, unit economics)
     → Strategy (roadmap, phasing, MVP scope)
     → [CHECKPOINT: User reviews strategy]
     → UI/UX (wireframes, user flows, design system)
     → Dev (architecture, tech stack, implementation plan)
     → SQL Admin (data model, schema design)
     → [CHECKPOINT: User reviews technical design]
     → Cyber Security (threat model, compliance requirements)
     → Compliance (regulatory checklist, legal needs)
     → Naysayer (reviews everything, challenges assumptions)
     → [CHECKPOINT: User reviews risk assessment]
     → Marketing (positioning, pricing, launch plan)
     → Sales (revenue model, acquisition strategy)
     → [FINAL: Complete business + technical plan]
```

### "Fix my game and bring it to market"
```
User → Dev (assess current state, identify bugs, fix plan)
     → [CHECKPOINT: User approves fix priorities]
     → Dev (implement fixes)
     → UI/UX (polish, accessibility, onboarding)
     → [CHECKPOINT: User reviews game state]
     → Researcher (market analysis, comparable games, pricing)
     → Strategy (launch plan, platform selection)
     → Marketing (trailer, store listing, community building)
     → [FINAL: Launch-ready plan]
```

## Design Principles
- **Checks and balances** — No agent's output is final without review by at least one other agent
- **Naysayer is mandatory** — Every major deliverable gets devil's advocate review
- **Human in the loop** — Checkpoints at every phase transition, user can intervene anytime
- **Cost aware** — Use Haiku for routine agent work, Sonnet for analysis, Opus sparingly
- **Incremental** — Each agent produces a concrete artifact, not just commentary
- **Adaptable** — Agent roster and workflow are configurable per task type
