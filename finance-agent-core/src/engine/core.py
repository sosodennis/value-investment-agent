import networkx as nx
from typing import Callable, Any, Dict, List, Optional
import inspect

class CalculationGraph:
    """
    A deterministic calculation engine based on NetworkX.
    Nodes represent financial metrics.
    Edges represent dependencies.
    """
    def __init__(self, name: str):
        self.name = name
        self.graph = nx.DiGraph()
        self.functions: Dict[str, Callable] = {}

    def add_node(self, name: str, func: Optional[Callable] = None):
        """
        Add a node to the graph.
        If func is provided, it's a calculated node.
        If func is None, it's an input node (value must be provided at runtime).
        """
        self.graph.add_node(name)
        if func:
            self.functions[name] = func
            # Inspect function signature to determine dependencies
            sig = inspect.signature(func)
            for param in sig.parameters:
                self.graph.add_edge(param, name)

    def validate(self):
        """Check for cycles and missing dependencies."""
        if not nx.is_directed_acyclic_graph(self.graph):
            raise ValueError(f"Graph {self.name} contains cycles.")
        
    def calculate(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the calculation graph.
        :param inputs: Dictionary of input values for leaf nodes.
        :return: Dictionary containing all calculated values.
        """
        results = inputs.copy()
        
        # Get topological sort of the graph
        try:
            execution_order = list(nx.topological_sort(self.graph))
        except nx.NetworkXUnfeasible:
            raise ValueError("Graph contains cycles, cannot execute.")

        for node in execution_order:
            if node in results:
                continue # Already provided in inputs
            
            if node in self.functions:
                func = self.functions[node]
                # Gather arguments
                sig = inspect.signature(func)
                args = {}
                for param in sig.parameters:
                    if param not in results:
                        raise ValueError(f"Missing dependency '{param}' for node '{node}'")
                    args[param] = results[param]
                
                # Execute function
                try:
                    results[node] = func(**args)
                except Exception as e:
                    raise RuntimeError(f"Error calculating node '{node}': {str(e)}")
            else:
                # If it's not a function calculation, it SHOULD have been in inputs
                pass
                
        return results

    def get_inputs(self) -> List[str]:
        """Return a list of required input nodes (nodes with 0 in-degree)."""
        return [n for n, d in self.graph.in_degree() if d == 0]
