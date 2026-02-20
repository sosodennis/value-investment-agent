from __future__ import annotations


def resolve_end_goto(target: str, *, end_node: str) -> str:
    """Normalize sentinel END target to the framework END node value."""
    return end_node if target == "END" else target


def resolve_end_goto_fanout(
    target: str | list[str], *, end_node: str
) -> str | list[str]:
    """Normalize END target for single-hop or fan-out transitions."""
    if isinstance(target, list):
        return [resolve_end_goto(node, end_node=end_node) for node in target]
    return resolve_end_goto(target, end_node=end_node)
