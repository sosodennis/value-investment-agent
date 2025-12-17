import uuid
from src.workflow.graph import graph

def main():
    print("=== Starting Neuro-Symbolic Valuation Engine ===")
    
    # 1. Initialize Thread (for memory persistence)
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    
    # 2. Start Workflow
    initial_input = {
        "ticker": "CRM",
        "model_type": "saas"
    }
    
    print(f"User Request: Value {initial_input['ticker']} using {initial_input['model_type']} model.")
    
    # Run until interrupt
    # stream returns events. We iterate.
    current_values = None
    for event in graph.stream(initial_input, config=config):
        for key, value in event.items():
            print(f"\n[Node: {key}]")
            # print(value)
            if key == "auditor":
                 print(f"Audit Result: {value.get('audit_report')}")

    # 3. Handle Interrupt (HITL)
    snapshot = graph.get_state(config)
    if snapshot.next:
        print("\n>>> HITL INTERRUPT: Workflow paused before:", snapshot.next)
        print("Current State Params (Excerpt):")
        params = snapshot.values.get("params", {})
        print(f"Growth Rates: {params.get('growth_rates')}")
        print(f"WACC: {params.get('wacc')}")
        
        # Simulate Human Approval / Modification
        print("\n>>> User Action: Approving parameters...")
        
        # Resume execution
        # We can pass None to just resume, or update state.
        # graph.invoke(None, config=config) -> This might restart?
        # Use Command or just stream from current config?
        # In idiomatic LangGraph, we just call stream/invoke again with Command or None?
        # Actually, stream(None, config) should resume.
        
        print("\n>>> Resuming Workflow...")
        # Note: If we need to update state, we would pass Command(update=...)
        # Here we just assume approval.
        
        for event in graph.stream(None, config=config):
             for key, value in event.items():
                print(f"\n[Node: {key}]")
                if key == "calculator":
                    print(f"Valuation Result: {value.get('valuation_result')}")

    print("\n=== Workflow Complete ===")

if __name__ == "__main__":
    main()
