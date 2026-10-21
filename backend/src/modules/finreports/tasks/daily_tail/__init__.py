"""The provisional daily tail: settlement days the weekly report has not reached.

WB forms a realization report per day as well as per week — ``period: "daily"``
on the same two methods, defaulting to ``weekly``, which is the whole reason this
existed unread until 2026-09-23. A daily report is stamped ``date_to + 1`` and
served that morning, against the one-to-eight days a weekly report takes, so this
lane is what lets the P&L reach **yesterday** instead of last Sunday.

It is deliberately an addition rather than a replacement, and the shape follows
from what is and is not proven:

* **The rows are the same rows.** Measured over the closed week 14.09-20.09 on
  one workspace: seven daily reports and weekly report 989438999 are the same 4 424
  rows sharing their ``rrdId`` one for one, every money column summing to the same
  figure. So they go into ``logistics_transaction`` like any others and the P&L
  picks them up by ``rr_dt`` — there is nothing to change on the read side, and
  the rollup rebuilds any day the detail upsert touches or whose row count it
  disagrees with.
* **What is NOT proven is whether a daily report is revised after WB serves it.**
  So this lane never writes a weekly header, never moves the settlement
  watermark, and never claims a day is settled. It records what it fetched and
  :func:`verify_daily_tail` re-reads it a day later to find out.
* **It walks only ahead of the settled frontier.** A day at or behind the
  frontier belongs to the weekly lane, which is the authority; re-fetching it
  here would do nothing but flip those rows' ``report_id`` to a daily id.
* **A fleet sweep takes the weekly harvest's own lock.** Both lanes spend the
  same one-request-a-minute WB buckets, so two sweeps at once would only make
  each 429 the other. Losing the lock costs a tick, and on the six days a week
  the weekly tick finds nothing, the lock is free.
* **A run scoped to one workspace does not.** That is what «Обновить» enqueues,
  and under the shared lock the button would answer «already running» and fetch
  nothing exactly when the hourly sweep is in flight — the one case it exists
  for. A scoped run spends one seller's budget, WB's buckets are per token, and
  pacing is the rate gate's job; its own lock only stops two clicks on the same
  workspace walking it twice.
"""

from src.modules.finreports.tasks.daily_tail.harvest import (
    harvest_daily_tail,
    tail_one_workspace,
)
from src.modules.finreports.tasks.daily_tail.verify import verify_daily_tail

__all__ = ["harvest_daily_tail", "tail_one_workspace", "verify_daily_tail"]
