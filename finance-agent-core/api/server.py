import sys
import os
import json
import uvicorn
from typing import Optional, Dict, Any, List
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# Add the project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.workflow.state import AgentState
from src.workflow.graph import graph
from langgraph.types import Command
from langchain_core.messages import HumanMessage
from src.workflow.interrupts import InterruptValue

app = FastAPI(
    title="Neuro-Symbolic Valuation Engine API",
    version="2.0",
    description="Pure FastAPI implementation for FinGraph Valuation Agent (Path B)",
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

class RequestSchema(BaseModel):
    message: Optional[str] = None
    thread_id: str
    resume_payload: Optional[Dict[str, Any]] = None

@app.get("/")
async def health_check():
    return {"status": "ok", "mode": "Pure FastAPI (Path B)"}

@app.post("/stream")
async def stream_agent(body: RequestSchema):
    """
    Unified endpoint for sending messages OR resuming execution.
    Eliminates the need for separate /resume and /chat endpoints.
    """
    print(f"📥 Received Request: ThreadID={body.thread_id}, Message={body.message}, Resume={body.resume_payload}")
    
    config = {"configurable": {"thread_id": body.thread_id}}
    
    # Decision Logic: Are we starting or resuming?
    input_data = None
    if body.resume_payload:
        # We are resuming: Wrap payload in Command
        # The payload from frontend usually comes as { "approved": true } etc.
        print("🔄 Resuming with Command...")
        input_data = Command(resume=body.resume_payload)
    elif body.message:
        # We are starting: Wrap message in state dict.
        # Also populate 'user_query' as the planner relies on it.
        print("▶️ Starting new run with Message...")
        # Use strong typing with AgentState
        input_data = AgentState(
            messages=[HumanMessage(content=body.message)],
            user_query=body.message
        ).model_dump()
    else:
        # It's possible to call with just thread_id to resume without payload if the graph allows, 
        # but for our use case we expect either message or resume payload.
        raise HTTPException(status_code=400, detail="Must provide message or resume_payload")

    async def event_generator():
        try:
            # 1. Stream events using the v2 API
            print("🌊 Starting Event Stream...")
            async for event in graph.astream_events(input_data, config=config, version="v2"):
                # Filtering logic: Don't stream internal LLM generation (e.g. JSON extraction)
                # metadata.get("langgraph_node") gives the node name.
                node_name = event.get("metadata", {}).get("langgraph_node", "")
                event_type = event["event"]

                # List of nodes whose generation we want to HIDE from the chat UI
                HIDDEN_NODES = {"extraction", "searching", "deciding", "clarifying", "auditor"}
                
                # If we are streaming tokens from a hidden node, skip yielding
                if event_type == "on_chat_model_stream" and node_name in HIDDEN_NODES:
                     continue
                
                # Standardize event serialization
                def json_serializable(obj):
                    try:
                        if hasattr(obj, "model_dump"):
                            return obj.model_dump()
                        if hasattr(obj, "dict"):
                            return obj.dict()
                        return str(obj)
                    except Exception:
                        return str(obj)

                # Send standard events
                yield f"event: {event['event']}\ndata: {json.dumps(event, default=json_serializable)}\n\n"
            
            print("✅ Event Stream Completed. Checking for interrupts...")

            # 2. Explicit Interrupt Detection
            # After the run completes (or pauses), check the state explicitly
            snapshot = await graph.aget_state(config)
            
            if snapshot.next:
                print(f"⏸️ Graph Paused. Next nodes: {snapshot.next}")
                # Check for interrupts in the tasks
                current_interrupts = []
                for task in snapshot.tasks:
                    if task.interrupts:
                        # task.interrupts is a tuple of Interrupt objects
                        for i in task.interrupts:
                            try:
                                # Validate and serialize using our strong types
                                val = InterruptValue.model_validate(i.value)
                                current_interrupts.append(val.model_dump())
                            except Exception:
                                # Fallback if unknown interrupt type
                                current_interrupts.append(i.value)
                
                if current_interrupts:
                    print(f"⚠️ Interrupts Detected: {current_interrupts}")
                    # Emit a custom 'interrupt' event to the client
                    yield f"event: interrupt\ndata: {json.dumps(current_interrupts)}\n\n"
            else:
                print("🏁 Graph Execution Finished (No pending steps).")

        except Exception as e:
            print(f"❌ Error during streaming: {str(e)}")
            error_event = {"error": str(e)}
            yield f"event: error\ndata: {json.dumps(error_event)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)