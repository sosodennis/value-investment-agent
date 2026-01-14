# Value Investment Agent (Neuro-Symbolic Valuation Engine)

The **Value Investment Agent** is a Neuro-Symbolic Valuation Engine that decouples semantic reasoning (Probabilistic) from financial calculations (Deterministic). It employs a multi-agent system to perform comprehensive fundamental analysis, extract financial parameters, and calculate intrinsic value using precise financial models.

## 🚀 Overview

Traditional LLM-based financial tools often hallucinate numbers or struggle with complex arithmetic. This project solves that by separating the "thinking" from the "math":
*   **Agents (Neuro)**: Understand user intent, research companies, analyze news, and extract specific valuation parameters from unstructured data (10-Ks, 10-Qs).
*   **Engine (Symbolic)**: A deterministic calculation layer that accepts validated parameters and executes financial models (e.g., DCF, DDM) with mathematical precision.

## ✨ Key Features

### 🤖 Multi-Agent Workflow
The system is orchestrated by **LangGraph** and consists of specialized agents:
1.  **Fundamental Analysis**: Performs comprehensive ticker search, identifies the correct company, and gathers core financial data.
2.  **Financial News Research**: Analyzes market sentiment and gathers recent news relevant to the valuation.
3.  **Debate**: A multi-agent debate session to challenge assumptions and refine the investment thesis.
4.  **Executor (Parameter Extraction)**: Scans financial documents to extract specific inputs required for the selected valuation model (e.g., "Risk-Free Rate", "Growth Rate").
5.  **Auditor**: Validates the extracted parameters, checks for logical inconsistencies, and flags potential hallucinations.
6.  **Approval (Human-in-the-Loop)**: An interactive step where the user reviews the assumptions and extracted parameters before the final calculation is performed.
7.  **Calculator**: Executes the deterministic financial model using the approved inputs.

### 📊 Valuation Models
Currently supported models:
*   **SaaS FCFF**: Free Cash Flow to Firm model tailored for Software-as-a-Service companies.
*   **Bank DDM**: Dividend Discount Model for valuing financial institutions.

## 🏗️ Architecture

*   **Frontend**: [Next.js 16](https://nextjs.org/), React 19, TypeScript.
*   **Backend**: Python, [FastAPI](https://fastapi.tiangolo.com/), [LangGraph](https://langchain-ai.github.io/langgraph/).
*   **Database**: PostgreSQL (for state persistence and checkpointing).
*   **Infrastructure**: Docker Compose.

## 🛠️ Getting Started

### Prerequisites
*   [Docker](https://www.docker.com/) and [Docker Compose](https://docs.docker.com/compose/)
*   An API key for [OpenRouter](https://openrouter.ai/) (to access LLMs like GPT-4, Claude, etc.)

### 1. Environment Setup
Create a `.env` file in the root directory:

```bash
touch .env
```

Add your OpenRouter API key and base URL:

```env
OPENROUTER_API_KEY=your_openrouter_api_key_here
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
# Optional: Database overrides (defaults provided in docker-compose)
# POSTGRES_USER=postgres
# POSTGRES_PASSWORD=postgres
# POSTGRES_DB=langgraph
```

### 2. Run with Docker (Recommended)
Build and start the entire stack:

```bash
docker-compose up --build
```

Access the application:
*   **Frontend**: [http://localhost:3000](http://localhost:3000)
*   **Backend API**: [http://localhost:8000](http://localhost:8000)
*   **API Documentation**: [http://localhost:8000/docs](http://localhost:8000/docs)

### 3. Manual Development (Optional)

#### Backend (`finance-agent-core`)
The backend uses `uv` for dependency management.

```bash
cd finance-agent-core
uv venv
source .venv/bin/activate
uv sync
uv run start
```
*   Run tests: `uv run pytest`

#### Frontend (`frontend`)
The frontend uses `npm`.

```bash
cd frontend
npm install
npm run dev
```

## 🤝 Contributing
Contributions are welcome! Please follow the coding standards outlined in the project.
1.  Fork the repository.
2.  Create a feature branch.
3.  Commit your changes.
4.  Open a Pull Request.
