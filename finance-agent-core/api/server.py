import sys
import os
# Add the project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from typing import Any, Dict
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from langserve import add_routes
from langgraph.graph import StateGraph
from langgraph.types import Command
from src.workflow.graph import graph
import uvicorn
import json
from fastapi.responses import StreamingResponse

app = FastAPI(
    title="Neuro-Symbolic Valuation Engine API",
    version="1.0",
    description="API for the FinGraph Valuation Agent",
)

# Set all CORS enabled origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# --- 🛠️ THE FIX: Configuration Modifier ---
def per_req_config_modifier(config: Dict[str, Any], request: Request) -> Dict[str, Any]:
    """
    Extracts the thread_id from HTTP headers and injects it into the LangGraph config.
    This guarantees the Checkpointer always has a thread_id, regardless of the JSON body.
    """
    # 1. Look for 'X-Thread-ID' in the request headers
    thread_id = request.headers.get("X-Thread-ID")
    
    if thread_id:
        # 2. If found, inject it into the configurable dictionary
        config = config.copy()
        if "configurable" not in config:
            config["configurable"] = {}
        config["configurable"]["thread_id"] = thread_id
        print(f"✅ Injected Thread ID from Header: {thread_id}")
    else:
        # Optional: Log a warning if no ID is found
        print("⚠️ Warning: No X-Thread-ID header found.")
        
    return config

@app.get("/")
async def redirect():
    return {"message": "FinGraph API is running. Go to /agent/playground for interactive testing."}

# Add LangServe routes with the modifier
add_routes(
    app,
    graph,
    path="/agent",
    per_req_config_modifier=per_req_config_modifier
)

# --- 🚀 NEW: Specialized Resume Endpoint for HITL ---
@app.post("/agent/resume")
async def resume_agent(request: Request):
    """
    Enterprise Best Practice: Specialized endpoint for resuming with Command.
    This handles the complexity of mapping a simple JSON payload to a LangGraph Command.
    """
    data = await request.json()
    thread_id = request.headers.get("X-Thread-ID") or data.get("thread_id")
    payload = data.get("payload") # The resume payload (e.g. { "approved": true })

    if not thread_id:
        return {"error": "X-Thread-ID header or thread_id in body is required"}

    config = {"configurable": {"thread_id": thread_id}}

    async def event_generator():
        # Use astream_events or astream for consistency with LangServe
        # Here we use astream_events v2 to match what the SDK expects
        
        def json_serializable(obj):
            try:
                if hasattr(obj, "model_dump"):
                    return obj.model_dump()
                if hasattr(obj, "dict"):
                    return obj.dict()
                return str(obj)
            except Exception:
                return str(obj)

        async for event in graph.astream_events(Command(resume=payload), config=config, version="v2"):
            yield f"event: {event['event']}\ndata: {json.dumps(event, default=json_serializable)}\n\n"

        # --- 🛠️ FIX: Manually check for interrupts and inject event ---
        snapshot = await graph.aget_state(config)
        if snapshot.next:
            for task in snapshot.tasks:
                if task.interrupts:
                    formatted_interrupts = [{"value": i.value} for i in task.interrupts]
                    chunk = {"__interrupt__": formatted_interrupts}
                    event = {
                        "event": "on_chain_stream",
                        "data": {"chunk": chunk},
                        "run_id": "manual_interrupt_injection",
                        "name": "interrupt_injector",
                        "tags": [],
                        "metadata": {}
                    }
                    yield f"event: {event['event']}\ndata: {json.dumps(event, default=json_serializable)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)