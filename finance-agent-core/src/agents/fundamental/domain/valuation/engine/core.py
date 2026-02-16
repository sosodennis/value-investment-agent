import inspect
from collections.abc import Callable

import networkx as nx

from src.shared.kernel.traceable import (
    ComputedProvenance,
    ManualProvenance,
    TraceableField,
)

Scalar = float | int
Vector = list[float]
TraceScalar = TraceableField[float]
TraceVector = TraceableField[list[float]]
CalcValue = Scalar | Vector | TraceScalar | TraceVector


class CalculationGraph:
    """
    A deterministic calculation engine based on NetworkX.
    Nodes represent financial metrics.
    Edges represent dependencies.
    """

    def __init__(self, name: str):
        self.name = name
        self.graph = nx.DiGraph()
        self.functions: dict[str, Callable[..., CalcValue]] = {}

    def add_node(self, name: str, func: Callable[..., CalcValue] | None = None):
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

    def calculate(
        self, inputs: dict[str, CalcValue], trace: bool = False
    ) -> dict[str, CalcValue]:
        """
        Execute the calculation graph.
        :param inputs: Dictionary of input values for leaf nodes.
        :return: Dictionary containing all calculated values.
        """
        if trace:
            results: dict[str, CalcValue] = {
                k: self._to_traceable(k, v) for k, v in inputs.items()
            }
        else:
            results = inputs.copy()

        # Get topological sort of the graph
        try:
            execution_order = list(nx.topological_sort(self.graph))
        except nx.NetworkXUnfeasible as e:
            raise ValueError("Graph contains cycles, cannot execute.") from e

        for node in execution_order:
            if node in results:
                continue  # Already provided in inputs

            if node in self.functions:
                func = self.functions[node]
                # Gather arguments
                sig = inspect.signature(func)
                args: dict[str, CalcValue] = {}
                trace_inputs: dict[str, TraceableField] = {}
                for param in sig.parameters:
                    if param not in results:
                        raise ValueError(
                            f"Missing dependency '{param}' for node '{node}'"
                        )
                    param_value = results[param]
                    if isinstance(param_value, TraceableField):
                        trace_inputs[param] = param_value
                        args[param] = param_value.value  # unwrap
                    else:
                        if trace:
                            trace_inputs[param] = self._to_traceable(param, param_value)
                        args[param] = param_value

                # Execute function
                try:
                    output = func(**args)
                except Exception as e:
                    raise RuntimeError(
                        f"Error calculating node '{node}': {str(e)}"
                    ) from e
                results[node] = self._wrap_output(node, output, trace_inputs)
            else:
                # If it's not a function calculation, it SHOULD have been in inputs
                pass

        return results

    def get_inputs(self) -> list[str]:
        """Return a list of required input nodes (nodes with 0 in-degree)."""
        return [n for n, d in self.graph.in_degree() if d == 0]

    @staticmethod
    def _to_traceable(name: str, value: CalcValue) -> TraceableField:
        if isinstance(value, TraceableField):
            return value
        return TraceableField(
            name=name,
            value=value,
            provenance=ManualProvenance(description="Input provided"),
        )

    def _wrap_output(
        self,
        node: str,
        output: CalcValue,
        trace_inputs: dict[str, TraceableField],
    ) -> CalcValue:
        if isinstance(output, TraceableField):
            return output
        if not trace_inputs:
            return output

        expression = self.functions[node].__name__
        provenance = ComputedProvenance(
            op_code=node,
            expression=expression,
            inputs=trace_inputs,
        )
        return TraceableField(name=node, value=output, provenance=provenance)
