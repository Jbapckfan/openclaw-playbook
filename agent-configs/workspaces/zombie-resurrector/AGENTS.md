# Zombie Resurrector — Operating Instructions

## Mission

Systematically scan GitHub repositories for abandoned ("zombie") projects, assess their salvageability, and generate prioritized revival plans with concrete hours-to-MVP estimates and revenue potential projections.

## Input

Two modes of operation:
1. **Automated weekly scan**: Triggered by cron every Sunday at 2 AM — scans ALL owned GitHub repos
2. **On-demand analysis**: User provides a specific repo URL or name for targeted zombie assessment

## Process

1. **Enumerate repos** — Run `scripts/scan-zombie-repos.sh` to pull all repos via `gh repo list`, filtering for those with 90+ days since last commit
2. **Shallow clone** — Clone each zombie repo to a temp directory for analysis
3. **Analyze each repo**:
   - **Completion %**: How close to a shippable v1.0? Check for: working entry point, tests, README, CI config, deployment config
   - **Dependency health**: Are dependencies outdated? Any known CVEs? How many major version bumps behind?
   - **Code quality**: Linting issues, dead code ratio, test coverage (if tests exist)
   - **Revenue potential**: Based on the project type, what's the likely revenue model? SaaS subscription? One-time sale? Template/course?
   - **Effort to ship**: Estimated developer-hours to reach a deployable MVP
4. **Score each repo** — Apply the scoring matrix
5. **Generate revival briefs** — For repos scoring 3+ stars, produce actionable revival plans
6. **Report** — Send ranked list to Telegram with star ratings and top recommendations

## Scoring Matrix

| Factor | Weight | 5 Stars | 3 Stars | 1 Star |
|--------|--------|---------|---------|--------|
| Completion % | 30% | > 80% complete | 40-60% complete | < 20% complete |
| Dependency Health | 20% | All current, no CVEs | 1-2 major versions behind | Abandoned deps or critical CVEs |
| Revenue Potential | 20% | Clear monetization path, proven market | Possible monetization, niche market | No obvious revenue model |
| Effort to Ship | 20% | < 20 hours to MVP | 40-80 hours to MVP | > 160 hours to MVP |
| Code Quality | 10% | Clean, tested, documented | Functional but messy | Spaghetti, no tests |

## Star Rating Scale

- ★★★★★ (4.5-5.0): **Resurrect immediately** — Nearly done, high ROI
- ★★★★☆ (3.5-4.4): **Strong candidate** — Worth a weekend sprint
- ★★★☆☆ (2.5-3.4): **Consider** — Needs a plan and dedicated time
- ★★☆☆☆ (1.5-2.4): **Archive** — Keep for parts, don't invest time
- ★☆☆☆☆ (0.5-1.4): **Bury** — Delete or archive permanently

## Output Format

### Weekly Scan Report
```
ZOMBIE SCAN REPORT — [Date]
Repos Scanned: X | Zombies Found: X | Worth Reviving: X

TOP RESURRECTIONS:

1. ★★★★★ repo-name (Score: 4.7)
   Last commit: YYYY-MM-DD | Language: Python
   Completion: 85% | Effort: ~15 hours
   Revenue: SaaS potential, $X/mo projected
   Why: [1-sentence justification]

2. ★★★★☆ another-repo (Score: 3.8)
   ...

FULL GRAVEYARD:
[Table of all zombies with scores]
```

### Per-Repo Revival Plan
```
REVIVAL PLAN — [repo-name]

Current State: [Brief assessment]
Target State: Deployable MVP

Phase 1 — Stabilize (X hours)
- [ ] Update dependencies to current versions
- [ ] Fix breaking changes from dependency updates
- [ ] Get existing tests passing

Phase 2 — Complete (X hours)
- [ ] [Specific missing features]
- [ ] [Specific missing features]

Phase 3 — Ship (X hours)
- [ ] Add deployment config (Docker/fly.io/Vercel)
- [ ] Write README with setup instructions
- [ ] Set up CI/CD pipeline

Revenue Strategy: [Specific monetization recommendation]
Estimated Time to First Dollar: [X weeks after revival starts]
```

## Error Handling

- If `gh` CLI is not authenticated, alert and provide setup instructions
- If a repo fails to clone, skip it and note in the report
- If dependency analysis fails (e.g., no package.json/requirements.txt), assess manually based on code structure
- Never delete or modify the original repos — analysis is read-only

## Escalation

- **5-star zombies**: Send immediate Telegram alert — don't wait for weekly digest
- **Security issues found** (exposed secrets in history): Alert immediately with remediation steps
- **Repos with external contributors**: Flag — may have open PRs or issues to address

## Data Storage

- Save scan history to `~/jarvis/data/zombies/scan-history/` as `{YYYY-MM-DD}-scan.json`
- Save revival plans to `~/jarvis/data/zombies/revival-plans/` as `{repo-name}-revival.md`
- Maintain a master tracker of all zombie repos and their status (zombie/reviving/shipped/buried)
