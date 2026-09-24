"""The token bucket's arithmetic, as it runs inside Redis.

Four scripts over one hash per ``(surface, endpoint, token)``. They are here as
a set rather than beside their callers because they are one mechanism read four
ways, and the invariants that matter are BETWEEN them: `PEEK` must agree with
`ACQUIRE` about the same bucket while writing nothing, and both must let
`PENALISE`'s ``blocked_until`` outrank the refill estimate — our refill is a
constant that knows nothing about a block, and the two disagreed by minutes in
production. WB's own number is the better of the two and still not the truth:
`PENALISE` treats it as a floor and says why.

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
local reserve_ms = tonumber(ARGV[4])
if reserve_ms == nil then
  reserve_ms = 0
end
local blocked_until = tonumber(state[3])
if blocked_until ~= nil and blocked_until > now_ms then
  -- Plus the reserve: `penalise` restores the tokens as of the moment the block
  -- lifts, so that instant is when one becomes available and a reserving caller
  -- owes its wait from there. PEEK says the same, and the two must agree.
  return blocked_until - now_ms + reserve_ms
end
local tokens = tonumber(state[1])
local ts = tonumber(state[2])
if tokens == nil or ts == nil then
  tokens = capacity
  ts = now_ms
  -- Written NOW, before the reserve is tested, because the reserve is measured
  -- from `ts`. Left in a local the key stays absent on the refusal path below,
  -- so the next caller starts the clock again from ITS own `now` and the
  -- reserve never elapses. That is not theoretical: it put NEVA's lane in a
  -- 30-second refusal loop on 2026-09-15 that could not have ended.
  redis.call('HSET', KEYS[1], 'tokens', tokens, 'ts', ts)
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
  -- Untouched bucket: a token is there for the taking, but a reserving caller
  -- still owes its wait. Answering 0 here is what let a refused tick re-enqueue
  -- itself every 30 s against an `acquire` that was never going to let it
  -- through — PEEK and ACQUIRE must describe the same bucket.
  return reserve_ms
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

#: Shut this endpoint until WB says it reopens — and then some.
#:
#: Called with the wait WB itself demanded (`X-Ratelimit-Retry`). That number is
#: the best information available and it is still **a floor rather than the
#: truth**: measured on prod 2026-09-09, a 429 demanding 1594 s was followed
#: 900 s later by a second demanding exactly 694 s, the remainder — WB was
#: counting down from its own longer window the whole time. Measured again on
#: 2026-09-12/14, a request 18 minutes after a good page drew 2762 s where the
#: published reset is 917.
#:
#: So two corrections are applied here rather than believed away:
#:
#: * ``ARGV[4]`` is a MARGIN multiplier on what WB said. Waiting longer than
#:   demanded costs one delayed report; waiting less costs a restarted block,
#:   and the blocks escalate.
#: * ``last_block_ms`` is the ESCALATION MEMORY. A 429 arriving when no block of
#:   ours stood means our model of WB's window was too short — the margin was
#:   not enough — so the new block is at least twice the last one we served.
#:   That is the loop the settlement endpoint fell into on 2026-09-17, where
#:   28 197 s became 18 624 s became 302 940 s: each of our estimates expired
#:   early, each probe restarted WB's window harder, and nothing in our state
#:   remembered that the previous guess had already been proved wrong.
#:
#: The memory decays with the key, whose TTL outlives the block it records by
#: the block's own length. A one-off block therefore stops shaping the endpoint
#: roughly one block after it lifts, instead of poisoning it for ever.
#:
#: `tokens` is restored to capacity as of the moment the block lifts, because
#: WB's reset IS the start of a fresh window; trickling from a refill estimate
#: would keep punishing the caller after WB had stopped.
#:
#: Returns ``{until_ms, block_ms}`` so the caller can record what it actually
#: served — the metric records what WB demanded, and the two differ on purpose.
PENALISE_LUA = """
local now = redis.call('TIME')
local now_ms = tonumber(now[1]) * 1000 + math.floor(tonumber(now[2]) / 1000)
local demanded_ms = tonumber(ARGV[1])
local capacity = tonumber(ARGV[2])
local grace_ms = tonumber(ARGV[3])
local margin = tonumber(ARGV[4])
if margin == nil or margin < 1 then
  margin = 1
end
local state = redis.call('HMGET', KEYS[1], 'blocked_until', 'last_block_ms')
local prev_until = tonumber(state[1])
local last_block = tonumber(state[2])
local block_ms = demanded_ms * margin
-- Nothing of ours stood in the way and WB refused anyway: the previous block
-- was too short, whatever WB said about it then or says about it now.
if (prev_until == nil or prev_until <= now_ms) and last_block ~= nil and last_block > 0 then
  block_ms = math.max(block_ms, last_block * 2)
end
-- A block already standing is never shortened. WB restarting its window is the
-- normal case here, and taking the smaller of the two numbers would hand the
-- next caller a slot inside a window that is demonstrably still open.
if prev_until ~= nil and prev_until > now_ms + block_ms then
  block_ms = prev_until - now_ms
end
local until_ms = now_ms + block_ms
redis.call('HSET', KEYS[1],
  'tokens', capacity, 'ts', until_ms,
  'blocked_until', until_ms, 'last_block_ms', block_ms)
-- The key must outlive the block by a wide margin, because its expiry is read
-- as «no block» — the single state we may never enter by accident. Sized from
-- the block itself rather than from the bucket's refill, which knows nothing
-- about it.
redis.call('PEXPIRE', KEYS[1], math.ceil(block_ms + grace_ms))
return {tostring(until_ms), tostring(block_ms)}
"""


#: Record a penalty block against an endpoint for EVERY token, not just the one
#: that earned it.
#:
#: The bucket above is keyed per seller token, and for the ordinary budget that
#: is right: the fleet has probed this endpoint on five tokens within the same
#: second, twenty-one times a day, for months, and has not been refused for it.
#: A strictly per-IP budget of one request per 917 s could not have survived
#: that, so the ordinary metering is very probably per token.
#:
#: **The punishment is not.** On 2026-09-17 five distinct token fingerprints
#: ended up holding `blocked_until` values 0.77 s apart — one shared countdown,
#: five separate 429s. Whatever WB meters per token, it appears to *refuse* per
#: caller. Left per-token, that shape is a cascade: the fleet walk is
#: sequential, so seller 1 is refused and blocked, seller 2 knows nothing about
#: it and is refused and blocked, and five escalating blocks are earned where
#: one was deserved.
#:
#: So the block is written twice — once to the token's own bucket, once here,
#: to a key naming only the surface and the endpoint. It is never shortened:
#: whichever refusal reaches furthest into the future is the one that stands.
#:
#: The endpoint this was measured on is `reportDetailByPeriod`, which the
#: service left on 2026-09-22. No gate passes ``shared_block`` any more
#: (2026-09-24); the script stays for the next endpoint that refuses this way.
SHARE_BLOCK_LUA = """
local now = redis.call('TIME')
local now_ms = tonumber(now[1]) * 1000 + math.floor(tonumber(now[2]) / 1000)
local until_ms = tonumber(ARGV[1])
local grace_ms = tonumber(ARGV[2])
local current = tonumber(redis.call('GET', KEYS[1]))
if current == nil or current < until_ms then
  redis.call('SET', KEYS[1], until_ms, 'PX', math.ceil(until_ms - now_ms + grace_ms))
end
return tostring(until_ms)
"""

#: Milliseconds the endpoint stays shut for everyone, 0 when it does not.
#:
#: Read through Redis rather than compared against the caller's clock for the
#: same reason every script here reads ``TIME``: a bucket consulted by the API,
#: the worker and beat is exactly where container clock drift would show up as
#: two processes disagreeing about whether a window is open.
SHARED_BLOCK_LEFT_LUA = """
local now = redis.call('TIME')
local now_ms = tonumber(now[1]) * 1000 + math.floor(tonumber(now[2]) / 1000)
local until_ms = tonumber(redis.call('GET', KEYS[1]))
if until_ms == nil or until_ms <= now_ms then
  return 0
end
return until_ms - now_ms
"""


__all__ = [
    "ACQUIRE_SLOT_LUA",
    "CLAMP_SLOTS_LUA",
    "PEEK_SLOT_LUA",
    "PENALISE_LUA",
    "SHARED_BLOCK_LEFT_LUA",
    "SHARE_BLOCK_LUA",
]
