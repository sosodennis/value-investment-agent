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
        
        # Check if this is a planner_human_review interrupt (ticker selection)
        if "planner_human_review" in snapshot.next:
            print("\n=== Ticker Selection Required ===")
            candidates = snapshot.values.get("ticker_candidates", [])
            
            if candidates:
                print("\nMultiple ticker candidates found:")
                for idx, candidate in enumerate(candidates):
                    symbol = candidate.get("symbol", "N/A")
                    name = candidate.get("name", "N/A")
                    exchange = candidate.get("exchange", "N/A")
                    confidence = candidate.get("confidence", 0.0)
                    print(f"  [{idx}] {symbol} - {name} ({exchange}) - Confidence: {confidence:.2f}")
                
                # Ask user to select
                selection = input("\nEnter the number of your choice (or press Enter to use default): ").strip()
                
                if selection.isdigit() and 0 <= int(selection) < len(candidates):
                    selected_idx = int(selection)
                    selected_symbol = candidates[selected_idx].get("symbol")
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
            params = snapshot.values.get("params", {})
            print(f"Growth Rates: {params.get('growth_rates')}")
            print(f"WACC: {params.get('wacc')}")
            print("\n>>> User Action: Approving parameters...")
        
        # Resume execution
        print("\n>>> Resuming Workflow...")
        
        for event in graph.stream(None, config=config):
             for key, value in event.items():
                print(f"\n[Node: {key}]")
                if key == "calculator":
                    print(f"Valuation Result: {value.get('valuation_result')}")

    print("\n=== Workflow Complete ===")

if __name__ == "__main__":
    main()
