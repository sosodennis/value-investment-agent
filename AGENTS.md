# **AGENTS.md**

## **Part 1: Domain Agents (Neuro-Symbolic Valuation Engine)**

### **Overview**

The **Neuro-Symbolic Valuation Engine** employs a hierarchical multi-agent system to decouple semantic parameter extraction (Probabilistic/Neuro) from financial calculations (Deterministic/Symbolic). This section defines the personas, responsibilities, and interaction patterns of the functional agents.

### **1. The Strategist (Fundamental Analysis Subgraph)**

**Role**: Architect & Decision Maker

*   **Responsibility**: Defines *what* we are valuing and *how*.
    *   **Intent Extraction**: Identifies the target company and user intent from the initial query.
    *   **Dual-Channel Search**: Simultaneously queries Yahoo Finance (structured) and Web Search (unstructured) to find the correct ticker symbol, handling ambiguity (e.g., GOOG vs GOOGL).
    *   **Financial Health Check**: Connects to SEC EDGAR to retrieve XBRL financial statements (Balance Sheet, Income Statement, Cash Flow) and generates a health report.
    *   **Model Selection**: Determines the appropriate valuation model (e.g., SaaS FCFF vs. Bank DDM) based on the company's industry profile and financial data.
*   **Key Nodes**: `extraction`, `searching`, `deciding`, `financial_health`, `model_selection`, `clarifying`.

### **2. The Scout (Financial News Research Subgraph)**

**Role**: Market Intelligence

*   **Responsibility**: Gathers and synthesizes qualitative market sentiment.
    *   **Search Funnel**: Executes a multi-stage funnel:
        1.  **Search**: Finds recent news across multiple timeframes.
        2.  **Selector**: Uses an LLM to filter for high-relevance articles.
        3.  **Fetch**: Retrieves and cleans full-text content in parallel.
        4.  **Analyst**: Performs deep sentiment analysis on each article (utilizing FinBERT + LLM hybrid approach).
        5.  **Aggregator**: Synthesizes a final weighted sentiment score and extracts key themes.
*   **Key Nodes**: `search_node`, `selector_node`, `fetch_node`, `analyst_node`, `aggregator_node`.

### **3. The Council (Debate Subgraph)**

**Role**: Critical Review Board

*   **Responsibility**: Challenges assumptions through adversarial discourse.
    *   **Bull Agent**: Argues the optimistic case for the stock.
    *   **Bear Agent**: Argues the pessimistic/risk-focused case.
    *   **Moderator**: Oversees the debate, evaluates arguments, and produces a final synthesis.
    *   **Structure**: Supports blind debates (parallel execution) and sequential cross-examination rounds.
*   **Key Nodes**: `debate_aggregator`, `bull`, `bear`, `moderator`.

### **4. The Researcher (Executor Node)**

**Role**: Parameter Hunter

*   **Responsibility**:
    *   Takes the selected valuation model and financial context.
    *   Extracts the specific numeric parameters required for that model (e.g., *Risk-Free Rate*, *Beta*, *Terminal Growth Rate*).
    *   Generates or retrieves "Citations" for extracted values.
*   **Output**: Structured `ExtractionOutput`.

### **5. The Compliance Officer (Auditor Node)**

**Role**: Risk Control & QA

*   **Responsibility**:
    *   Validates extracted parameters against logical business rules (e.g., "Terminal growth rate cannot exceed GDP growth").
    *   Flags hallucinations or data inconsistencies.
*   **Output**: `AuditOutput` (Pass/Fail with messages).

### **6. Human-in-the-Loop (Approval)**

**Role**: Final Sign-off

*   **Trigger**: Before the deterministic calculation runs.
*   **Action**: The user reviews the resolved ticker, selected model, extracted parameters, and audit results. The process pauses until explicit approval is granted.

### **7. The Engine (Calculator Node)**

**Role**: Deterministic Execution

*   **Responsibility**:
    *   Receives validated parameters.
    *   Executes the `CalculationGraph` (a DAG of pure Python functions).
    *   Produces the final Intrinsic Value and sensitivity analysis.
    *   **Zero-Hallucination Guarantee**: No LLMs are used in this step.

---

### **Interaction Flow**

```mermaid
graph TD
    Start([Start]) --> FA[Fundamental Analysis<br/>(The Strategist)]

    subgraph "Neuro (Probabilistic Agents)"
        FA --> FNR[Financial News Research<br/>(The Scout)]
        FNR --> Debate[Debate<br/>(The Council)]
        Debate --> Executor[Executor<br/>(The Researcher)]
        Executor --> Auditor[Auditor<br/>(The Compliance Officer)]
    end

    Auditor --> Approval{Human Approval}

    Approval -->|Approved| Calc[Calculator<br/>(The Engine)]
    Approval -->|Rejected| End([End])

    subgraph "Symbolic (Deterministic)"
        Calc
    end

    Calc --> End
```

---

## **Part 2: Coding & Development Rules**

The canonical frontend and backend coding standards are [`docs/frontend-guideline.md`](docs/frontend-guideline.md) and [`docs/backend-guideline.md`](docs/backend-guideline.md). This section keeps only finance-domain constraints that those guides do not define.

### **1. Traceability Architecture (Provenance)**

To ensure every number is auditable, the system uses a `TraceableField` generic with specific `Provenance` types:

*   **XBRLProvenance**: Data sourced directly from SEC filings.
    *   Fields: `concept` (XBRL tag), `period`.
*   **ComputedProvenance**: Data derived from other fields.
    *   Fields: `expression` (Formula), `inputs` (Source fields).
*   **ManualProvenance**: Data provided or overridden by human/agent assumptions.
    *   Fields: `description` (Reasoning), `author`, `modified_at`.

**Example:**
```python
class TraceableField(BaseModel, Generic[T]):
    value: T | None
    provenance: XBRLProvenance | ComputedProvenance | ManualProvenance
```

### **2. Agent and Calculation Boundaries**

*   **Separation of Concerns**: Keep "Thinking" (Agents) separate from "Math" (Calculations).
*   **Tool Usage**: Agents should rely on tools (e.g., `edgartools`, `yfinance`) rather than internal knowledge.
*   **Error Handling**: Fail gracefully with explicit error messages in the Agent State.

### **3. Issue and Verification Gates**

*   When implementation encounters an engineering compromise against issue acceptance criteria, canonical contracts, security/ownership boundaries, or shared system architecture, immediately record it in a linked GitHub issue labeled `blocker`.
*   Resolve the underlying design gap in the owning system layer. A workaround or UI-only concealment does not resolve a blocker.
*   Do not mark blocked work VERIFIED, merge it, or close its issue until the actual diff, relevant tests, Docker health, and end-to-end behavior have been inspected and pass.

## **Part 3: Project Skill Routing**

*   **Task tracking**: Use Codex's task plan/checklist for multi-step work. Do not add or use a separate task-management protocol or project-local task-tracking artifacts in this repository.
*   **Pstack**: Use pstack as the general workflow for exploration, design, implementation, and review. The finance-agent skills below are project-specific supplements, not competing general workflows. Load only the relevant supplement for a task.
*   **Issues and worktrees**: Follow [`docs/issue-worktree-lifecycle.md`](docs/issue-worktree-lifecycle.md) for parent integration branches, child issue delivery, verification, issue closure, and branch/worktree cleanup.
*   **Docker development and parallel worktrees**: Use `docker-development` for project-specific Compose configuration, startup, builds, test stacks, resource checks, and cleanup. Give each active worktree a unique Compose project name and host ports. Inspect the current Compose files because the service set can change.
*   **Agent implementation detail**: Use `agent-implementation-extractor` for evidence-backed deep dives into `finance-agent-core/src/agents/*`, including state, LangGraph flow, and agent boundaries. Use pstack `how` for broader or non-agent subsystem walkthroughs.
*   **Agent failures and regressions**: Use `agent-debug-review-playbook` when diagnosing failures, degraded paths, regressions, or agent-specific quality risks; use pstack's general debugging skills for other work.
*   **Architecture compliance**: `architecture-standard-enforcer` is the single project entry point for checking agent architecture rules. The referenced architecture standard is the source of hard rules.
*   **Skill upkeep after architecture changes**: After completing a change that materially changes agent layer topology, subdomain ownership, workflow/state contracts, runtime boundaries, or cross-agent responsibilities, run `architecture-skill-maintainer`. It checks all three project-specific skills and updates only the guidance made stale by the change. A design proposal without an implemented architecture change does not trigger this step.

## **Part 4: Disposable Legacy Data During Refactors**

*   During a large refactor or model/schema migration, optimize for the target architecture and the quality of the new data model. If disposable legacy data blocks the target model, delete the old records and rebuild them in the target shape; do not spend implementation time on compatibility migrations, aliases, backfills, or shims whose only purpose is preserving obsolete disposable data.
*   Before deleting anything, verify that the data belongs to the disposable local/refactor environment, record the reset scope and rebuild source, and regenerate the canonical fixtures/seeds. Never delete production or explicitly retained staging data implicitly; if retained data cannot satisfy the target model, stop and record a linked `blocker` issue with an explicit reset decision and recovery evidence.
