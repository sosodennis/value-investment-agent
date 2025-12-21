import uuid
from src.workflow.graph import graph

def main():
    print("=== Starting Neuro-Symbolic Valuation Engine ===")
    
    # 1. Initialize Thread (for memory persistence)
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    
    # 2. Start Workflow
    user_query = input("\nWhat stock would you like to valuate? (e.g., 'Value Tesla')\n> ")
    
    initial_input = {
        "user_query": user_query
    }
    
    print(f"\nProcessing request: {user_query}")
    
    # Run until interrupt
    # stream returns events. We iterate.
    for event in graph.stream(initial_input, config=config):
        for key, value in event.items():
            print(f"\n[Node: {key}]")
            # print(value)
            if key == "auditor":
                 print(f"Audit Result: {value.get('audit_output')}")

    # 3. Handle Interrupt (HITL)
    snapshot = graph.get_state(config)
    if snapshot.next:
        print("\n>>> HITL INTERRUPT: Workflow paused before:", snapshot.next)
        
        # Access state (assuming Pydantic object)
        state_values = snapshot.values
        # If it happens to be a dict (defensive), handle it? 
        # But we assume Pydantic object given StateGraph setup.
        
        # Check if this is a planner_human_review interrupt (ticker selection)
        if "planner_human_review" in snapshot.next:
            print("\n=== Ticker Selection Required ===")
            candidates = state_values.ticker_candidates if hasattr(state_values, 'ticker_candidates') else state_values.get("ticker_candidates", [])
            
            if candidates:
                print("\nMultiple ticker candidates found:")
                for idx, candidate in enumerate(candidates):
                    # candidate might be TickerCandidate object or dict
                    symbol = candidate.symbol if hasattr(candidate, 'symbol') else candidate.get("symbol", "N/A")
                    name = candidate.name if hasattr(candidate, 'name') else candidate.get("name", "N/A")
                    exchange = candidate.exchange if hasattr(candidate, 'exchange') else candidate.get("exchange", "N/A")
                    confidence = candidate.confidence if hasattr(candidate, 'confidence') else candidate.get("confidence", 0.0)
                    print(f"  [{idx}] {symbol} - {name} ({exchange}) - Confidence: {confidence:.2f}")
                
                # Ask user to select
                selection = input("\nEnter the number of your choice (or press Enter to use default): ").strip()
                
                if selection.isdigit() and 0 <= int(selection) < len(candidates):
                    selected_idx = int(selection)
                    selected_candidate = candidates[selected_idx]
                    selected_symbol = selected_candidate.symbol if hasattr(selected_candidate, 'symbol') else selected_candidate.get("symbol")
                    print(f"\n>>> User selected: {selected_symbol}")
                    
                    # Update state before resuming
                    graph.update_state(config, {"selected_symbol": selected_symbol})
                else:
                    print("\n>>> No valid selection. Using default (top candidate).")
            else:
                print("\n>>> No candidates available. Proceeding with default behavior.")
        
        # Check if this is a calculator interrupt (parameter approval)
        elif "calculator" in snapshot.next:
            print("\n=== Parameter Review ===")
            extraction_output = state_values.extraction_output if hasattr(state_values, 'extraction_output') else state_values.get("extraction_output")
            params = extraction_output.params if extraction_output else {}
            
            print(f"Growth Rates: {params.get('growth_rates')}")
            print(f"WACC: {params.get('wacc')}")
            print("\n>>> User Action: Approving parameters...")
        
        # Resume execution
        print("\n>>> Resuming Workflow...")
        
        for event in graph.stream(None, config=config):
             for key, value in event.items():
                print(f"\n[Node: {key}]")
                if key == "calculator":
                    print(f"Valuation Result: {value.get('calculation_output')}")

    print("\n=== Workflow Complete ===")

if __name__ == "__main__":
    main()
