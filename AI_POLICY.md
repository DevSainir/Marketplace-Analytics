# AI policy

Marketplace Analytics was built with [Claude Code](https://claude.com/claude-code), Anthropic's AI
coding agent. It was my first project with an AI agent. This file says how AI is used in this
repository, and what working with it was like.

## How AI is used here

- **Claude wrote the code; I made the engineering decisions.** I chose the stack, set the direction
  of the architecture, laid the foundation and decided how the system is built.
- **The agent works from context kept in the repository.** [`CLAUDE.md`](CLAUDE.md) gives the
  overview; seven skills in [`.claude/skills/`](.claude/skills/) hold the rules for each kind of
  work — backend and frontend architecture, the design system, phone layout, testing, security and
  the git workflow. The agent loads the one a task calls for.
- **Tests check what the agent did with that context.** Most of the rules in the skills are also
  tests or lint rules — module boundaries, the 500-line ceiling per file, tenant isolation, metrics
  without tenant labels — so a rule the agent forgets fails the build instead of slipping through.
  Ruff, mypy `--strict`, ESLint and Prettier run on every commit.
- **Hooks keep the agent on the workflow.** [`.claude/hooks/`](.claude/hooks/) refuse
  branch-creating commands and pushes to anything but `main`.
- **Every finished task is recorded** in [`docs/JOURNAL.md`](docs/JOURNAL.md).

## What it was like

Speed and quality surprised me most. With the direction set right, Claude works through details
that would take me a long time to get into. It can also assume too much, or miss a solution that is
obvious to a person — and its writing tends to be more convoluted than it needs to be. I got used
to that.

The lesson I took is that the truth is in the context: the more precisely it is chosen, the more
precisely the task gets done. Skills and documentation give the agent its context; tests are how I
check what it did with it.

### The mistake that taught me the most

The P&L in the [README](README.md#the-pl-is-checked-against-the-money) looked right and was not:
our payout disagreed with the one Wildberries reports. The first fix Claude wrote passed on the eight
reports we had Wildberries' totals for, and was still wrong. Tests could not have caught it — they
checked the rule as written, not the money Wildberries actually paid. Only the comparison with
Wildberries' own figure did, and now it runs on every report.

### Where the context came from

The front end is where I learned to give Claude context. For a long time, working on the UI with it
frustrated me — until I gave it a clear design system, a skill describing how a designer works, and
references to match. Claude found the references online itself; I only pointed the way. After that
the front end stopped frustrating me.

### What I don't know yet

I understand most of the code — more than 90%, by my own estimate — but not every line, and I'm
closing the gaps.
