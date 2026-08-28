"""Golden-set routing-accuracy regression tests for skill search.

Skill selection (MCP clade_search_skills AND the trigger vocabulary that
Claude Code itself routes on) depends on each SKILL.md keeping its
`description:` and `when_to_use:` frontmatter intact. Commit 2dba7b9 fixed a
regression where 7 blog-* descriptions were silently truncated — caught only
by manual inspection. This file is the CI gate for that class of drift:

1. A golden set of realistic user queries (English + Chinese triggers) must
   each surface the expected skill in the TOP 3 results of
   mcp_server.search_skills() when run against the REPO's configs/skills/.
2. Disambiguation cases: sibling-heavy queries must rank the RIGHT skill #1
   (e.g. "audit learned correction rules" → audit, not seo-audit/ads-audit).
3. Structural guard: every skill has a substantive description (≥ 40 chars) —
   catches the truncation class directly, before it shows up as bad routing.

search_skills() scoring (see mcp_server.py): whitespace-tokenized query terms,
substring match against lowercased "name description when_to_use", score =
number of matched terms, ties broken alphabetically by name. Chinese queries
therefore work only if the phrase literally appears in the frontmatter —
every Chinese case below was verified against configs/skills/<name>/SKILL.md.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIGS_SKILLS = REPO_ROOT / "configs" / "skills"

pytest.importorskip("mcp")
sys.path.insert(0, str(REPO_ROOT / "orchestrator"))
try:
    import mcp_server
finally:
    sys.path.pop(0)


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def repo_skills() -> list[dict]:
    """All skills loaded from the REPO's configs/skills (not ~/.claude)."""
    old = mcp_server.SKILLS_DIR
    mcp_server.SKILLS_DIR = CONFIGS_SKILLS
    try:
        skills = mcp_server.load_skills()
    finally:
        mcp_server.SKILLS_DIR = old
    assert len(skills) >= 100, (
        f"only {len(skills)} skills loaded from {CONFIGS_SKILLS} — "
        "wrong directory or mass frontmatter breakage"
    )
    return skills


def _top_names(query: str, skills: list[dict], n: int) -> list[str]:
    return [s["name"] for s in mcp_server.search_skills(query, skills)][:n]


# ─── Golden set: query → expected skill in TOP 3 ─────────────────────────────
# Queries are realistic keyword-ish phrases a user would type (2-5 terms),
# NOT reverse-engineered exact matches — the point is that natural trigger
# vocabulary keeps routing.

GOLDEN_TOP3: list[tuple[str, str]] = [
    # workflow / session lifecycle
    ("split changes into commits and push", "commit"),
    ("autonomous supervisor worker loop", "loop"),
    ("keep iterating in this session until done", "iloop"),
    ("execute TODO.md steps unattended", "batch-tasks"),
    ("context getting full save state", "handoff"),
    ("resume where I left off", "pickup"),
    ("what should I work on next", "next"),
    ("what's going on right now", "status"),
    ("are you stuck still working", "poke"),
    # engineering skills
    ("diagnose root cause of a bug", "investigate"),
    ("review pull request feedback", "review-pr"),
    ("audit external upstream skill repo", "equip"),
    ("scaffold a new skill with triggers", "skill-new"),
    ("create git worktree parallel session", "worktree"),
    ("decompose goal into parallel worker tasks", "orchestrate"),
    ("verify behavior anchors after autonomous run", "verify"),
    ("record a learning remember this pattern", "learn"),
    ("weekly retrospective commit stats", "retro"),
    ("research competitors and external tools", "research"),
    # environment / tooling
    ("toggle statusline quota indicator", "slt"),
    ("check API usage quota", "minimax-usage"),
    ("switch provider to minimax", "provider"),
    # content / marketing families
    ("write a new blog article", "blog-write"),
    ("blog post AI citation readiness score", "blog-geo"),
    ("technical seo core web vitals", "seo"),
    ("check page title and meta description", "seo-page"),
    ("AI Overviews Perplexity llms.txt", "seo-geo"),
    ("full website seo audit crawl", "seo-audit"),
    ("paid advertising campaign audit", "ads"),
    ("Google Ads Performance Max quality score", "ads-google"),
    ("Meta ads pixel CAPI Advantage+", "ads-meta"),
    ("generate an image design a logo", "banana"),
    ("design UI component with the design system", "frontend-design"),
    ("优化网页 UI", "frontend-design"),
    ("优化 iOS 原生 App", "frontend-design"),
    ("优化 Windows 桌面软件", "frontend-design"),
    ("redesign Electron desktop app UI", "frontend-design"),
    # Chinese triggers — substring match requires the phrase to literally
    # appear in the skill's frontmatter (verified by grep, all unique).
    ("提交", "commit"),
    ("恢复", "pickup"),
    ("卡住了吗", "poke"),
    ("下一步做什么", "next"),
    ("自动循环", "loop"),
    ("批量执行", "batch-tasks"),
    ("报错 修复", "investigate"),
    ("保存 交接", "handoff"),
    ("新建技能", "skill-new"),
]


@pytest.mark.parametrize(
    "query,expected",
    GOLDEN_TOP3,
    ids=[f"{expected}<-{query}" for query, expected in GOLDEN_TOP3],
)
def test_golden_query_surfaces_skill_in_top3(repo_skills, query, expected):
    top3 = _top_names(query, repo_skills, 3)
    assert expected in top3, (
        f"routing drift: query {query!r} no longer surfaces {expected!r} "
        f"in top 3 (got {top3}) — check {expected}/SKILL.md description/"
        f"when_to_use for lost trigger vocabulary"
    )


# ─── Disambiguation: right sibling must rank FIRST ───────────────────────────
# These queries sit in crowded families where the wrong sibling matching
# first would send users (and MCP clients) to the wrong skill entirely.

DISAMBIGUATION_RANK1: list[tuple[str, str]] = [
    # the corrections-rules meta-audit, NOT seo-audit / ads-audit. Both
    # siblings carry "NOT for the corrections-rules meta-audit" in their
    # when_to_use — search_skills strips such negative clauses (see
    # _NEGATIVE_CLAUSE_RE), so the bare query must rank /audit first.
    ("audit corrections rules", "audit"),
    ("audit learned correction rules", "audit"),
    # background goal-file loop, NOT the in-session /iloop
    ("goal file converge background", "loop"),
    # full-site crawl audit, NOT the /seo umbrella or /seo-page
    ("site seo health score crawl", "seo-audit"),
    # scaffolding a first-party skill, NOT /generate-hook (hooks) and NOT
    # /equip (absorbing external skill repos) — both named in skill-new's
    # NOT-for clauses, which scoring strips. ("create a new skill" can only
    # TIE frontend-design — its description legitimately contains "create"
    # and "skill" — and ties break alphabetically, so use queries skill-new
    # wins outright.)
    ("add a new skill", "skill-new"),
    ("write a new slash command", "skill-new"),
    # interface-design umbrella: platform-specific UI requests must beat ads,
    # localization, and design-system siblings that also mention app/UI terms.
    ("优化手机端 UI", "frontend-design"),
    ("优化 iOS 原生 App", "frontend-design"),
    ("优化 Android App 界面", "frontend-design"),
    ("优化 macOS 本地软件", "frontend-design"),
    ("优化 Windows 桌面软件", "frontend-design"),
    ("redesign Electron desktop app UI", "frontend-design"),
    ("build Flutter mobile interface", "frontend-design"),
]


@pytest.mark.parametrize(
    "query,expected",
    DISAMBIGUATION_RANK1,
    ids=[f"{expected}<-{query}" for query, expected in DISAMBIGUATION_RANK1],
)
def test_disambiguation_query_ranks_skill_first(repo_skills, query, expected):
    top = _top_names(query, repo_skills, 3)
    assert top and top[0] == expected, (
        f"disambiguation drift: query {query!r} ranks {top[:3]} — expected "
        f"{expected!r} first; a sibling skill's frontmatter now outscores it"
    )


# ─── Structural guard: descriptions stay substantive ────────────────────────


def test_negative_clauses_do_not_score():
    """A skill whose frontmatter says 'NOT for X (use /other)' must not match
    a query about X — the clause is disambiguation, not a trigger."""
    skills = [
        {
            "name": "wrong-sibling",
            "description": "Does something else entirely.",
            "when_to_use": "sibling things — NOT for quantum audits (use /right)",
        },
        {
            "name": "right",
            "description": "Runs quantum audits.",
            "when_to_use": "quantum audits",
        },
    ]
    names = [s["name"] for s in mcp_server.search_skills("quantum audits", skills)]
    assert names == ["right"], (
        f"negative clause scored as a trigger: {names} — _NEGATIVE_CLAUSE_RE "
        "in mcp_server.search_skills no longer strips 'NOT for …'"
    )


def test_every_skill_has_substantive_description(repo_skills):
    """Catches the 2dba7b9 truncation class directly: a silently truncated or
    emptied description drops below any plausible real description length.
    (Current repo minimum is 55 chars; threshold 40 leaves headroom without
    letting a truncated stub through.)"""
    weak = sorted(
        (s["name"], len(s["description"]), s["description"])
        for s in repo_skills
        if len(s["description"]) < 40
    )
    assert not weak, (
        "skills with missing/truncated descriptions (< 40 chars): "
        + "; ".join(f"{name} ({n} chars): {desc!r}" for name, n, desc in weak)
    )


def test_when_to_use_chinese_triggers_intact(repo_skills):
    """The Chinese trigger phrases the golden set depends on must stay in the
    frontmatter verbatim — substring matching gives no fuzzy fallback."""
    required = {
        "commit": "提交",
        "pickup": "恢复",
        "poke": "卡住了吗",
        "next": "下一步做什么",
        "loop": "自动循环",
        "batch-tasks": "批量执行",
        "investigate": "报错",
        "handoff": "交接",
        "equip": "装备",
        "frontend-design": "设计页面",
    }
    by_name = {s["name"]: s for s in repo_skills}
    missing = []
    for name, phrase in required.items():
        skill = by_name.get(name)
        if skill is None:
            missing.append(f"{name}: skill directory gone")
            continue
        hay = f"{skill['description']} {skill.get('when_to_use', '')}"
        if phrase not in hay:
            missing.append(f"{name}: lost Chinese trigger {phrase!r}")
    assert not missing, "; ".join(missing)
