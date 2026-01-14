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

### **1. Technology Stack & Style**

*   **Frameworks**: LangGraph (Orchestration), FastAPI (Serving), Pydantic (Validation), NetworkX (Calculation Engine).
*   **Style Guide**:
    *   **Strict Typing**: All function signatures must have type hints. No `Any`.
    *   **Pydantic V2**: Use `model_dump()` instead of `dict()`.

### **2. Traceability Architecture (Provenance)**

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

### **3. Code Generation Principles**

*   **Separation of Concerns**: Keep "Thinking" (Agents) separate from "Math" (Calculations).
*   **Tool Usage**: Agents should rely on tools (e.g., `edgartools`, `yfinance`) rather than internal knowledge.
*   **Error Handling**: Fail gracefully with explicit error messages in the Agent State.
