# **AGENTS.md**

## **Part 1: Domain Agents (Neuro-Symbolic Valuation Engine)**

### **Overview**

The **Neuro-Symbolic Valuation Engine** employs a multi-agent system to decouple semantic parameter extraction (Probabilistic) from financial calculations (Deterministic). This section defines the personas, responsibilities, and interaction patterns of the functional agents.

### **1. The Planner (Orchestrator)**

**Role**: System Architect & Router

* **Responsibility**:  
  * **Intent Extraction**: Parses user queries (e.g., "Value Tesla") to identify the company and potential model preference.  
  * **Comprehensive Ticker Search (Scout)**: 
      * **Dual-Channel Search**: Queries both reliable financial databases (Yahoo Finance) and Web Search simultaneously to ensure maximum coverage.
      * **Candidate Aggregation**: Merges results from both sources, filtering competitors via strict semantic rules.
  * **Ambiguity Resolution**: Detects multiple valid candidates (e.g., "Google" -> GOOG/GOOGL) and triggers human intervention.
  * **Financial Health Check**: After ticker resolution, fetches financial data from SEC EDGAR using `edgartools` and generates a comprehensive Financial Health Report covering 5 pillars: Liquidity, Solvency, Operational Efficiency, Profitability, and Cash Flow Quality.
  * **Model Selection (Strategist)**: Determines the industry sector and selects the appropriate valuation model (e.g., SaaS FCFF vs. Manufacturing DCF vs. Bank DDM), enhanced with financial health insights.  
* **Tools**: YFinance (Primary), WebSearch (Fallback), RAGSearch (Internal), edgartools (SEC EDGAR XBRL).

### **2. The Executor (Parameter Hunter)**

**Role**: Research Analyst

* **Responsibility**:  
  * Scans financial documents (10-K, 10-Q, Transcripts).  
  * Extracts specific parameters required by the selected model.  
  * Provides "Citations" for every extracted value (Source + Quote).  
* **Tools**: RAGSearch, WebSearch.

### **3. The Auditor (Compliance Officer)**

**Role**: Risk Control & Quality Assurance

* **Responsibility**:  
  * Validates the logical consistency of extracted parameters.  
  * Enforces hard constraints (e.g., terminal_growth_rate < GDP_growth).  
  * Flags "Hallucinations" or "Unrealistic Assumptions" for human review.  
* **Input**: Structured JSON from Executor.  
* **Output**: Validated JSON or Error Report.

### **4. Human-in-the-Loop (HITL) Checkpoints**

#### **A. Planner Clarification (Ambiguity Resolution)**

**Role**: Disambiguation

* **Trigger**: Planner finds multiple valid tickers or is unsure about the model.  
* **Action**: User selects the correct ticker/model or provides a new query.

#### **B. Final Review (Senior PM / Analyst)**

**Role**: Final Decision Maker

* **Responsibility**:  
  * Reviews the parameters prepared by the agents before calculation.  
  * Adjusts assumptions based on intuition or external knowledge.  
  * Resolves "Clean Surplus Violations" or audit flags.  
* **Interaction**: Interruption via LangGraph before the CalculationNode.

### **Interaction Flow**

graph TD  
    User[User Request] --> Planner  
      
    subgraph Planner_Workflow  
        Planner --> Extraction  
        Extraction --> Search  
        Search --> Decision  
        Decision --> FinancialHealth[Financial Health Check]  
        FinancialHealth --> ModelSelection[Model Selection]  
    end  
      
    Decision -->|Ambiguous?| Clarification[HitL: Clarification]  
    Clarification -->|User Input| Planner  
      
    ModelSelection -->|Resolved| Executor  
    Executor -->|Extract Params| Auditor  
    Auditor -->|Pass Validation| FinalReview[HitL: Final Review]  
    Auditor -->|Fail Validation| Executor  
    FinalReview -->|Approve/Modify| Calculator[Deterministic Engine]  
    Calculator -->|Result| User

## **Part 2: Coding & Development Rules**

This section dictates how AI Assistants and Developers should write code, structure files, and handle errors within the project.

### **1. Technology Stack & Style**

* **Language**: Python 3.10+ (Primary), TypeScript (Frontend/Dashboard if applicable).  
* **Package Manager**: `uv` for Python dependency management and virtual environments.  
* **Frameworks**:  
  * Orchestration: LangGraph (Functional API v0.2+).
  * Serving: Pure FastAPI (LangServe removed).
  * Data Validation: Pydantic (Strict typing is mandatory).  
  * Financial Data: edgartools (SEC EDGAR XBRL extraction).  
* **Style Guide**:  
  * Follow **PEP 8** for Python.  
  * Use **Snake_case** for variables/functions, **PascalCase** for classes.  
  * **Strict Typing (Zero Any Policy)**:  
    * **NO Any allowed**: The use of Any (Python) or any (TypeScript) is **STRICTLY FORBIDDEN**. Explicitly define types, use specific generics, or union types if necessary.  
    * **Type Hints**: All function signatures MUST have type hints (e.g., def calculate_wacc(beta: float, rm: float) -> float:).

### **2. Code Generation Principles**

**The AI Assistant must adhere to these principles when generating code:**

* **Modular Design**: Each agent (Planner, Executor, Auditor) should have its own module/file. Avoid monolithic scripts.  
* **Deterministic vs. Probabilistic Separation**:  
  * Code in calculator/ modules must be pure, deterministic Python functions (No LLM calls inside calculation logic).  
  * Code in agents/ modules manages LLM interactions and context.  
* **Error Handling**:  
  * Use try/except blocks specifically around external API calls.  
  * Implement **Exponential Backoff** for API rate limits.  
  * Never fail silently; raise custom exceptions (e.g., TickerNotFoundError, ValidationException).

### **3. Data Structure Standards (Pydantic Models)**

All data passed between agents must be strictly typed using Pydantic.

# Example Standard  
class ValuationParameter(BaseModel):  
    name: str = Field(..., description="Name of the financial parameter")  
    value: float = Field(..., description="The numerical value extracted")  
    source: str = Field(..., description="URL or Document Name")  
    confidence: float = Field(ge=0, le=1, description="Model confidence score")  
      
class FinancialReport(BaseModel):  
    ticker: str  
    fiscal_year: int  
    parameters: List[ValuationParameter]

### **4. Testing & Validation Rules**

* **Unit Tests**: Every calculation formula (DCF, WACC, etc.) must have a corresponding unit test in tests/calculations/.  
* **Agent Evaluation**: Use mock responses to test Agent logic. Do not hit live LLM APIs for CI/CD tests.  
* **Audit Trails**: All critical decisions (Planner model selection, Auditor flags) must be logged to a structured log file or database for debugging.

### **5. Documentation**

* **Docstrings**: Every class and public method must have a docstring (Google Style).  
* **Comments**: Comment complex financial logic (e.g., *Why* are we adjusting the risk-free rate here?). Do not comment obvious code.  
* **Sync Domain Agents**: Whenever a feature is implemented or modified, the **Part 1: Domain Agents (Neuro-Symbolic Valuation Engine)** section MUST be updated immediately to ensure the documentation reflects the latest agent behaviors and functional state.

### **6. Security & Keys**

* Never hardcode API keys (OpenAI, Tavily, etc.). Use os.getenv() and .env files.  
* Ensure no PII (Personally Identifiable Information) is processed unless explicitly authorized.

### **7. API Protocol (Custom Control Path)**

* **Architecture**: Pure FastAPI (Path B).
* **Endpoint**: Single unified endpoint `POST /stream`.
* **Request Schema**:
  ```json
  {
    "thread_id": "string",
    "message": "string (optional)",
    "resume_payload": "object (optional)"
  }
  ```
* **Streaming**: Server-Sent Events (SSE).
* **Interrupts**: Explicit `event: interrupt` emitted at the end of the stream if the graph pauses.
* **State Persistence**: MemorySaver (Currently) -> PostgresSaver (Future).