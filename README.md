<p align="center"><img src="frontend/public/favicon.svg" width="72" alt=""></p>

<h1 align="center">Marketplace Analytics</h1>

<p align="center">
  An analytics service for Wildberries sellers: finance and a daily ads-and-sales sheet that fills
  itself — every product, every day, by ad placement and against organic traffic.
</p>

<p align="center">In daily use since July 2026 · Python · FastAPI · PostgreSQL · Redis · Vue 3 · Docker</p>

<p align="center">
  <a href="#what-it-does">What it does</a> ·
  <a href="#try-it">Try it</a> ·
  <a href="#how-its-built">How it's built</a> ·
  <a href="docs/finreports/PNL.md">How the P&amp;L is derived</a> ·
  <a href="AI_POLICY.md">Building it with Claude</a>
</p>

<p align="center">
  <img src="https://github.com/user-attachments/assets/2c92d156-b7a8-46f3-babe-e13ba11810ae" width="800"
       alt="The daily sheet filled in overnight: one product, day by day, by ad placement and organic traffic">
</p>

## About

Selling on [Wildberries](https://www.wildberries.ru), a large Russian online marketplace, means
paying for ads in several placements at once and working out which of them paid off. The team this
was built for kept an Excel sheet for it: 18 numbers a day for every product. Marketplace Analytics
builds that sheet itself every night — all 18 numbers, from impressions and clicks to orders, spend
and ad cost, for every product and day, by placement and against organic traffic, next to prices and stock. The
finance side turns Wildberries' weekly settlement reports into a P&L.

Today a seller's team and several client businesses, each with 3 to 30 products, work in it. Every morning two managers used to
spend from 10 a.m. to noon filling in the sheet before the team could start on it; now it is
filled overnight, and the team starts with it at 10. Every campaign and price change a manager makes is
recorded on its day, with a history of who changed what, so the head of the business can see what
was done and what followed. And because stock, ads and the sales funnel sit on one page, an analyst
can trace clear cause and effect.

I have been its only engineer since July 2026: I designed the system and run it, and the code was
written by Claude Code under my direction — [who did what](#ai-usage).

## What it does

**Monitoring**

- **Daily sheet** — every product by day: 18 metrics split into ad placements and organic, with
  prices and stock. Cells edit like Excel; each day carries notes and the team's actions.
- **Summary** — the account's week: revenue, profit, orders, buyout rate, ad cost.
- **Heatmap** — every product × every day for any of 25 metrics.
- **Advertising** — where the ad money went, by bid type and placement.
- **A/B photo tests** — a product's main photo rotated across variants, each measured on its own
  window.

**Finance**

- **P&L** — built line by line from Wildberries' settlement rows, for the account and per product.
- **Stock balance** — where the money that has not moved is sitting: stock at cost, by warehouse.
- **Cost prices** — entered one by one or round-tripped through Excel.

Around both: several seller accounts per company, invitations, per-page access for managers and
read-only guests.

<details>
<summary>Screenshots</summary>

All figures are fabricated by the demo seed.

**Daily sheet** — one product by day: each ad placement against organic, then prices and stock.
![Daily sheet](docs/screenshots/monitoring.jpg)

**Summary** — the account's week at a glance, with daily charts.
![Summary](docs/screenshots/summary.jpg)

**P&L** — sales, logistics, deductions, cost of goods and the payout, then the same per product.
![P&L](docs/screenshots/pnl.jpg)

**Advertising** — where the ad money went, by bid type and placement.
![Advertising](docs/screenshots/advertising.jpg)

**Heatmap** — every product × every day for one metric.
![Heatmap](docs/screenshots/heatmap.jpg)

**A/B photo test** — each variant of the main photo measured on its own window.
![A/B test](docs/screenshots/ab-test.jpg)

</details>

## Try it

The whole stack runs locally on a fabricated shop — no Wildberries account needed. It takes Docker
with Compose v2, `make` and `curl`.

```bash
git clone https://github.com/DevSainir/Marketplace-Analytics.git
cd Marketplace-Analytics
cp backend/.env.example backend/.env
make demo
```

The first run builds three images and takes 3–5 minutes. Then open <http://localhost:8080> and sign
in as **demo@example.com** / **demo-password**. `make demo-down` removes it with its data.

## How it's built

A modular monolith: FastAPI and Celery workers, a Vue 3 single-page app, PostgreSQL and Redis, all
in Docker. One rule from the project's [security design](docs/security/SECURITY_DESIGN.md) runs
through it: **a control that cannot be forgotten beats one that must be remembered.**

### The P&L is checked against the money

*In short: a profit statement can add up and still be wrong, so every week it is compared with what
Wildberries actually pays — automatically.*

The P&L is built line by line from Wildberries' settlement rows, and most of its figures can only
be checked against each other. One cannot: the payout, which Wildberries reports itself. When I set
ours against it, they disagreed on reports that carried corrections. Claude's first fix, checked on
the eight reports we had Wildberries' totals for, passed — and was still wrong. Measured against
every report, the real rule showed up: Wildberries keeps a row's direction in the document type,
not in the operation, and the same operation arrives under both. Now the payout matches Wildberries
to the kopeck on every report checked, and every booked report is compared with Wildberries' own
payout, with an alert when they differ by more than a rouble. The price: the payout is the only figure an outside party
confirms; the rest of the statement rests on how it is derived
([how the P&L is derived](docs/finreports/PNL.md)).

### The database defends itself

*In short: several businesses share one database, so the database itself — not only the
application — keeps each one's data apart.*

One wrong query would show a seller someone else's numbers. Before the service went commercial I
spent a hardening pass on its security — vulnerabilities, resources, the database and its roles —
and studying it I came across row-level security and knew at once we needed it. Rather than trust
every query to filter
by account, the database enforces it too: the API connects as a role that owns none of the
tables, and on the tables that carry a seller account, row-level security lets it see only the
account the request is bound to. A request that reaches such a table with no account bound fails
loudly instead of returning nothing — an empty result would look like "no data" and invite someone
to remove the check. The price: the covered tables are a reviewed list rather than found
automatically, and the background worker still runs as the owner, because collecting data
legitimately crosses accounts. Pinned by
[`test_row_level_security.py`](backend/tests/integration/core/test_row_level_security.py).

## AI usage

This is my first project built with an AI agent. Claude Code wrote the code; I chose the stack, set
the architecture and made the engineering decisions — if Claude was the developer, I was the
engineer and the architect. What I learned is that the truth is in the context: skills and
documentation give the agent its context, and tests check what it did with it.

The rules the agent works by live in [`.claude/skills/`](.claude/skills/), and most of them are also
checks that fail the build: modules talk only through a public contract, no backend file grows past
500 lines and no Vue component past 250, imports stay absolute
([`test_module_boundaries.py`](backend/tests/unit/core/test_module_boundaries.py), ruff and ESLint
rules, [`architecture.spec.js`](frontend/tests/integration/architecture.spec.js)). The skill tells the
agent; the check holds it to it. Checks have limits too — the clearest case is the
[P&L](#the-pl-is-checked-against-the-money).

I understand most of the code — more than 90%, by my own estimate — but not every line, and I'm
closing the gaps. The whole story, mistakes included, is in [AI_POLICY.md](AI_POLICY.md).

## Why I built it

I was looking for a job when a Wildberries seller offered me a staff position to build this. I had
been programming for about four years, but never on anything this large. The hardest part was
believing I could pull it off: I had the skills and the knowledge, not the experience, and for a
while I was afraid it would not work. It did — through a good number of hard moments.

Before the first line I studied what the project would stand on: architecture patterns, which led
me to a modular monolith; clean architecture; JWT, which the sign-in is built on; linters and mypy,
which now run on every commit; and how Claude works with a codebase. That groundwork set a direction
I still follow. The rest I learned on a product people use every day: security, architecture that
scales, monitoring and alerting, running servers.

---

This repository is a cleaned copy of the production code: client data, credentials and
infrastructure details were removed, and everything the demo and screenshots show is fabricated.
No license is granted: the code is published to be read, not reused.
