from __future__ import annotations

import pytest

from src.shared.kernel.rate_limit import (
    InMemoryRateLimiter,
    RateLimiterUnavailable,
    RateLimitExceeded,
    RedisRateLimiter,
)


@pytest.mark.asyncio
async def test_in_memory_limiter_returns_bounded_retry_after_and_is_scoped() -> None:
    limiter = InMemoryRateLimiter()
    await limiter.check(key="org-a:user-a", limit=2, window_seconds=60)
    await limiter.check(key="org-a:user-a", limit=2, window_seconds=60)
    with pytest.raises(RateLimitExceeded) as caught:
        await limiter.check(key="org-a:user-a", limit=2, window_seconds=60)
    assert 1 <= caught.value.retry_after_seconds <= 60
    await limiter.check(key="org-b:user-a", limit=2, window_seconds=60)


class FakeRedis:
    def __init__(self, result: object) -> None:
        self.result = result
        self.calls: list[tuple[object, ...]] = []

    async def eval(self, *args: object) -> object:
        self.calls.append(args)
        return self.result

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_redis_limiter_uses_one_atomic_script_and_retry_ttl() -> None:
    redis = FakeRedis([0, 17])
    limiter = RedisRateLimiter(redis)
    with pytest.raises(RateLimitExceeded) as caught:
        await limiter.check(key="invite:org-a", limit=10, window_seconds=3600)
    assert caught.value.retry_after_seconds == 17
    assert len(redis.calls) == 1
    assert redis.calls[0][1:] == (
        1,
        "value-investment-agent:rate-limit:invite:org-a",
        3600,
        1,
        10,
    )


@pytest.mark.asyncio
async def test_redis_limiter_fails_closed_when_backend_is_unavailable() -> None:
    class BrokenRedis(FakeRedis):
        async def eval(self, *args: object) -> object:
            raise OSError("redis down")

    with pytest.raises(RateLimiterUnavailable):
        await RedisRateLimiter(BrokenRedis(None)).check(
            key="directory:user-a", limit=30, window_seconds=60
        )
