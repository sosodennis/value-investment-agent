import asyncio
import time
from typing import Annotated

import pytest
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from pydantic import BaseModel


class TestState(BaseModel):
    messages: Annotated[list, add_messages] = []


async def slow_node(state: TestState):
    print("--- Slow Node Start ---")
    await asyncio.sleep(1.0)
    print("--- Slow Node End ---")
    return {"messages": ["Slow done"]}


async def slow_follower(state: TestState):
    print("--- Slow Follower Run ---")
    return {"messages": ["Slow Follower done"]}


async def fast_node(state: TestState):
    print("--- Fast Node Start ---")
    await asyncio.sleep(0.1)
    print("--- Fast Node End ---")
    return {"messages": ["Fast done"]}


async def fast_follower(state: TestState):
    print(f"--- Fast Follower Run at {time.time()} ---")
    return {"messages": ["Fast Follower done"]}


builder = StateGraph(TestState)
builder.add_node("slow", slow_node)
builder.add_node("slow_follower", slow_follower)
builder.add_node("fast", fast_node)
builder.add_node("fast_follower", fast_follower)

builder.add_edge(START, "slow")
builder.add_edge(START, "fast")
builder.add_edge("slow", "slow_follower")
builder.add_edge("fast", "fast_follower")
builder.add_edge("slow_follower", END)
builder.add_edge("fast_follower", END)

graph = builder.compile()


@pytest.mark.anyio
async def test_blocking():
    print("TIMING START")
    start = time.time()

    events = []
    async for event in graph.astream_events({"messages": []}, version="v2"):
        if (
            event["event"] == "on_chain_start"
            and event["metadata"].get("langgraph_node") == "fast_follower"
        ):
            elapsed = time.time() - start
            print(f"Fast Follower Started at: {elapsed:.2f}s")
            events.append(("fast_follower_start", elapsed))

        if (
            event["event"] == "on_chain_end"
            and event["metadata"].get("langgraph_node") == "slow"
        ):
            elapsed = time.time() - start
            print(f"Slow Node Ended at: {elapsed:.2f}s")
            events.append(("slow_end", elapsed))

    fast_start = next((t for n, t in events if n == "fast_follower_start"), None)
    slow_end = next((t for n, t in events if n == "slow_end"), None)

    if fast_start is None or slow_end is None:
        print("❌ Test failed: Missing events")
        return

    # If Fast Follower started BEFORE Slow Ended (with margin), then NO BLOCKING.
    # If Fast Follower started AFTER Slow Ended, then BLOCKING OCCURRED.

    if fast_start < slow_end:
        print(
            f"✅ Fast Follower started ({fast_start:.2f}s) BEFORE Slow Node ended ({slow_end:.2f}s). No blocking."
        )
    else:
        print(
            f"❌ Fast Follower started ({fast_start:.2f}s) AFTER Slow Node ended ({slow_end:.2f}s). BLOCKING CONFIRMED."
        )


if __name__ == "__main__":
    asyncio.run(test_blocking())
