"""The token bucket's arithmetic, as it runs inside Redis.

Four scripts over one hash per ``(surface, endpoint, token)``. They are here as
a set rather than beside their callers because they are one mechanism read four
ways, and the invariants that matter are BETWEEN them: `PEEK` must agree with
`ACQUIRE` about the same bucket while writing nothing, and both must let
`PENALISE`'s ``blocked_until`` outrank the refill estimate — WB's own number is
the only trustworthy one, and the two disagreed by minutes in production.

Every script reads the clock with Redis's own ``TIME``. Container clocks drift,
and a bucket shared by the API, the worker and beat is exactly where that drift
would show up as two processes disagreeing about whether a window is open.
"""

from __future__ import annotations

#: Take a token, or report how many milliseconds until one exists. The Redis
#: server clock (``TIME``) is the reference so every process agrees without
#: trusting container clocks.
#:
#: ``ARGV[4]`` is the caller's RESERVE: milliseconds a token must already have
#: been sitting unclaimed before this caller may take it. Zero for work a person
#: is waiting on; non-zero for background walks, which is how a slow backfill
#: stops racing the hourly harvest for the same slot. It does not change how
#: many requests leave — the bucket alone decides that — only WHO gets them when
#: two callers want the same one.
ACQUIRE_SLOT_LUA = """
local now = redis.call('TIME')
local now_ms = tonumber(now[1]) * 1000 + math.floor(tonumber(now[2]) / 1000)
local capacity = tonumber(ARGV[1])
local refill_ms = tonumber(ARGV[2])
local ttl_ms = tonumber(ARGV[3])
local state = redis.call('HMGET', KEYS[1], 'tokens', 'ts', 'blocked_until')
-- A penalty block is WB's own number and outranks every estimate below it:
-- while it stands no token exists, however much time has passed. Without this
-- the bucket reopened after `refill_ms` — our guess — and the request landed
-- inside a block that WB then restarted (see `penalise`).
local blocked_until = tonumber(state[3])
if blocked_until ~= nil and blocked_until > now_ms then
  return blocked_until - now_ms
end
local reserve_ms = tonumber(ARGV[4])
if reserve_ms == nil then
  reserve_ms = 0
end
local tokens = tonumber(state[1])
local ts = tonumber(state[2])
if tokens == nil or ts == nil then
  tokens = capacity
  ts = now_ms
end
-- The moment a token exists, which is now when one already does and a refill
-- away when it does not. A reserving caller must let it sit that long again.
local available_at = ts
if tokens < 1 then
  available_at = ts + math.ceil((1 - tokens) * refill_ms)
end
local ready_at = available_at + reserve_ms
if now_ms < ready_at then
  redis.call('PEXPIRE', KEYS[1], ttl_ms)
  return ready_at - now_ms
end
local elapsed = now_ms - ts
if elapsed > 0 then
  tokens = math.min(capacity, tokens + elapsed / refill_ms)
  ts = now_ms
end
tokens = tokens - 1
redis.call('HSET', KEYS[1], 'tokens', tokens, 'ts', ts)
redis.call('PEXPIRE', KEYS[1], ttl_ms)
return 0
"""

#: How long until a token exists, **without taking one**. Same arithmetic as
#: `ACQUIRE_SLOT_LUA` and deliberately no writes: this answers a question for a
#: user staring at a button, and a peek that consumed a slot would spend the
#: harvest's budget every time somebody looked.
PEEK_SLOT_LUA = """
local now = redis.call('TIME')
local now_ms = tonumber(now[1]) * 1000 + math.floor(tonumber(now[2]) / 1000)
local capacity = tonumber(ARGV[1])
local refill_ms = tonumber(ARGV[2])
local reserve_ms = tonumber(ARGV[3])
if reserve_ms == nil then
  reserve_ms = 0
end
local state = redis.call('HMGET', KEYS[1], 'tokens', 'ts', 'blocked_until')
local blocked_until = tonumber(state[3])
if blocked_until ~= nil and blocked_until > now_ms then
  return blocked_until - now_ms + reserve_ms
end
local tokens = tonumber(state[1])
local ts = tonumber(state[2])
if tokens == nil or ts == nil then
  return 0
end
local available_at = ts
if tokens < 1 then
  available_at = ts + math.ceil((1 - tokens) * refill_ms)
end
local ready_at = available_at + reserve_ms
if now_ms >= ready_at then
  return 0
end
return ready_at - now_ms
"""

#: Clamp our bucket to what WB just said it has left. Never raises our estimate
#: above WB's: a header of 0 empties the bucket, so the next caller waits a
#: full refill instead of walking into a 500.
CLAMP_SLOTS_LUA = """
local now = redis.call('TIME')
local now_ms = tonumber(now[1]) * 1000 + math.floor(tonumber(now[2]) / 1000)
local remaining = tonumber(ARGV[1])
local ttl_ms = tonumber(ARGV[2])
local state = redis.call('HMGET', KEYS[1], 'tokens', 'ts')
local tokens = tonumber(state[1])
if tokens == nil or remaining < tokens then
  tokens = remaining
end
redis.call('HSET', KEYS[1], 'tokens', tokens, 'ts', now_ms)
redis.call('PEXPIRE', KEYS[1], ttl_ms)
return tostring(tokens)
"""

#: Shut this endpoint until WB says it reopens. Called with the wait WB itself
#: demanded (`X-Ratelimit-Retry`), which is the only trustworthy number here:
#: measured on prod 2026-09-09, a 429 demanding 1594 s was followed 900 s later
#: — one local refill — by a second 429 demanding exactly 694 s, the remainder.
#:
#: `tokens` is restored to capacity as of the moment the block lifts, because
#: WB's reset IS the start of a fresh window; trickling from a refill estimate
#: would keep punishing the caller after WB had stopped.
PENALISE_LUA = """
local now = redis.call('TIME')
local now_ms = tonumber(now[1]) * 1000 + math.floor(tonumber(now[2]) / 1000)
local block_ms = tonumber(ARGV[1])
local capacity = tonumber(ARGV[2])
local ttl_ms = tonumber(ARGV[3])
local until_ms = now_ms + block_ms
redis.call('HSET', KEYS[1], 'tokens', capacity, 'ts', until_ms, 'blocked_until', until_ms)
redis.call('PEXPIRE', KEYS[1], ttl_ms)
return tostring(until_ms)
"""


__all__ = [
    "ACQUIRE_SLOT_LUA",
    "CLAMP_SLOTS_LUA",
    "PEEK_SLOT_LUA",
    "PENALISE_LUA",
]
