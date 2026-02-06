# Backend Findings - 06/02/2026

## [P3] In-memory runtime state breaks scaling and resiliency
- File: /Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/api/server.py:81
- Summary: Active tasks, queues, replay buffers, and sequence counters are process-local. This won’t work with multiple workers or after a restart and will cause dropped events and orphaned streams. Move this state to a shared store (e.g., Redis) or an event bus and make thread state resumable across processes.

## [P2] Stream attachment can leak queues for unknown threads
- File: /Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/api/server.py:440
- Summary: `/stream/{thread_id}` always creates a queue even if the thread is unknown or not running. This can leave long-lived idle connections and memory growth. Validate thread existence and return a terminal event/404, or use timeout/heartbeat policy.

## [P2] /stream accepts empty inputs and starts jobs with `None`
- File: /Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/api/server.py:471
- Summary: If neither `message` nor `resume_payload` is provided, `input_data` becomes `None` and the task still starts. Return 400 with a clear response schema.
