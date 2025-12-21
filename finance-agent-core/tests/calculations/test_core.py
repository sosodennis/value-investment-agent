import pytest
from src.engine.core import CalculationGraph

def test_add_node_no_func():
    graph = CalculationGraph("test_graph")
    graph.add_node("input_a")
    assert "input_a" in graph.graph.nodes
    assert "input_a" not in graph.functions

def test_add_node_with_func():
    graph = CalculationGraph("test_graph")
    def add_one(x: int):
        return x + 1
    
    graph.add_node("input_a")
    graph.add_node("calc_b", add_one) # b = a + 1
    
    assert "calc_b" in graph.graph.nodes
    assert "calc_b" in graph.functions
    assert graph.graph.has_edge("x", "calc_b") # dependency detected via param name

def test_calculate_simple_flow():
    graph = CalculationGraph("test_graph")
    
    def double(val: int) -> int:
        return val * 2
        
    graph.add_node("input_val")
    graph.add_node("doubled", double)
    
    # Notice: 'double' takes 'val', so we must map input 'input_val' to 'val' or rename.
    # The current engine/core.py infers strict dependency by param name.
    # So if function is `double(val)`, it expects a node named `val`.
    
    # specialized test for current behavior
    graph_v2 = CalculationGraph("test_v2")
    graph_v2.add_node("val")
    graph_v2.add_node("doubled", double)
    
    result = graph_v2.calculate({"val": 5})
    assert result["doubled"] == 10

def test_cycle_detection():
    graph = CalculationGraph("cycle_graph")
    
    def func_a(b): return b
    def func_b(a): return a
    
    graph.add_node("a", func_a)
    graph.add_node("b", func_b)
    
    with pytest.raises(ValueError, match="contains cycles"):
        graph.validate()
