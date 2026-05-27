---
name: ads-attribution
description: "Cross-platform attribution health audit covering AdAttributionKit (iOS view-through 24h post-impression, WWDC 2025 configurable windows), GA4 attribution models (data-driven vs last-click), Consent Mode V2 enforcement, server-side attribution stitching, MMP integration health, and cross-device / cross-platform attribution. Use when user says attribution audit, attribution model, AdAttributionKit, AAK, view-through attribution, GA4 attribution, Consent Mode V2, conversion window, attribution window, MMP audit, AppsFlyer audit, Adjust audit, Branch audit, Singular audit, cross-device attribution, or cross-platform attribution."
user-invokable: false
tested_date: 2026-05-17
tested_with: claude-code v2.x
---

# Cross-Platform Attribution Health Audit

Attribution decay is the silent revenue killer of 2026 — Consent Mode V2 EEA
enforcement (Jul 21, 2025), iOS ATT, SKAdNetwork → AdAttributionKit migration,
and the death of third-party cookies have moved every advertiser's
attribution signal toward modeled, server-side, first-party data. Misaligned
attribution windows or unverified Consent Mode setups will mis-attribute
15-40% of conversions and silently waste budget.

## Process

1. Collect current attribution stack: GA4 property ID, Google Ads conversion
   actions, Meta CAPI config, Apple Ads / AdAttributionKit registration,
   MMP dashboard (AppsFlyer / Adjust / Branch / Singular), any sGTM container
2. Read `ads/references/conversion-tracking.md` for the cross-platform
   tracking baseline
3. Evaluate attribution health per surface (web, iOS app, Android app,
   server-side)
4. Score each surface PASS / WARNING / FAIL
5. Generate findings report with cross-channel attribution map and remediation
   plan

## What to Analyze

### iOS Attribution (AdAttributionKit + ATT)

- **AdAttributionKit registered** with Apple Ads (post-Apr 10, 2025 cutover);
  registration creates dual attribution with SKAdNetwork (SKAN v1-3)
- **View-through attribution** active — 24h post-impression view window
  configured on Apple Ads campaigns where applicable
- **Configurable attribution windows** (WWDC 2025): per-campaign window
  customization audited; overlapping re-engagement windows used for
  subscription / re-acquisition campaigns
- **Country code in postbacks** (WWDC 2025): enabled if you need geo
  attribution detail
- **ATT (App Tracking Transparency) opt-in rate** monitored; <30% opt-in
  means heavy reliance on SKAN/AAK + privacy threshold
- **Privacy threshold awareness** — low-volume campaigns may receive null
  postbacks; campaign consolidation recommended below 1k installs/week

### Web Attribution (GA4 + Google Ads + Meta CAPI)

- **GA4 attribution model**: Data-Driven (default for properties with enough
  data) vs Last-Click — confirm setting is intentional, not residue from a
  pre-2026 migration
- **Google Ads attribution model**: Data-Driven default; per-conversion
  override allowed but audit any Last-Click overrides for justification
- **Cross-channel attribution** in GA4: confirm Google Ads, Meta, LinkedIn,
  TikTok, Microsoft are integrated as platforms with consent + auto-tagging
- **Conversion windows per channel** appropriate to sales cycle:
  - E-commerce: 7-day click, 1-day view
  - B2B / lead gen: 30-90 day click, no view
  - SaaS subscription: 30 day click, 1-day view, plus offline conversion
    import for the activation event
- **Conversion lag analysis** run quarterly to validate window choice

### Consent Mode V2 (EU/EEA + recommended globally)

- **Consent Mode V2 active** (enforcement began Jul 21, 2025 for EEA/UK)
- **Advanced Mode** (not Basic) — Basic loses ~25% of EEA conversion signal
- **700+ ad clicks/day over 7 days per country/domain** threshold met for
  Advanced Mode behavioral modeling to activate
- **Signal recovery measured**: aim 15-25% conversion recovery vs pre-CMV2
  baseline
- **Consent banner** correctly reads CMV2 signals (not just GDPR boilerplate)

### Server-Side Attribution Stitching

- **First-party server logs** stored with `user_id` + `event_id` + timestamp
  + platform tag for every conversion event
- **MMP + first-party stitching**: MMP (AppsFlyer / Adjust / Branch /
  Singular) receives both client-side AND server-side events with shared
  `event_id` for deduplication
- **Server-side conversion import** to Google Ads (offline conversion import)
  and Meta (CAPI) within 72h of the conversion event
- **Hash quality**: email / phone fields SHA-256 hashed and lowercased
  before send; cross-platform hashing convention consistent
- **Deduplication rate** ≥90% (matched event_id between client + server)

### MMP Health (Mobile Apps)

- **MMP integrated** — AppsFlyer / Adjust / Branch / Singular set up before
  any paid campaigns launched
- **Apple Ads connected as a partner** in MMP dashboard
- **Post-install events sent back** to Apple Ads, Google UAC, Meta App
  Campaigns, TikTok (enables Maximize Conversions and ROAS bidding)
- **Event quality**: purchase, subscription_start, trial_start, or other
  revenue events tracked (not just install → registration)
- **Postback configuration**: SKAN/AAK conversion values map to meaningful
  user actions

### Cross-Device & Cross-Platform Attribution

- **Customer Match** lists synced to Google Ads, Meta (Customer File CA),
  LinkedIn Matched Audiences, TikTok Customer File for cross-device stitching
- **Enhanced Conversions** active for Google Ads (hashed first-party data,
  ~10% uplift on properly-implemented setups)
- **CAPI customer_information parameters** (`em`, `ph`, `fn`, `ln`, `ct`,
  `st`, `zp`, `external_id`) sent server-side to Meta
- **Privacy-safe identifiers** (Customer Match hashes, GAID/IDFA where
  permitted) included in conversion exports

## Key Thresholds

| Metric | Pass | Warning | Fail |
|--------|------|---------|------|
| GA4 attribution model | Data-Driven | Last-Click (intentional) | Last-Click (residual) |
| Consent Mode V2 | Advanced + verified | Advanced (unverified) | Basic / Not implemented |
| EMQ (Meta Purchase) | ≥8.0 | 6.0-7.9 | <6.0 |
| Event dedup rate | ≥90% | 70-89% | <70% |
| Server-side / client-side hit ratio | ≥80% | 50-79% | <50% |
| ATT opt-in (iOS) | ≥30% | 15-29% | <15% (heavy SKAN reliance) |
| Offline conversion import latency | <24h | 24-72h | >72h |
| Customer Match list freshness | <7 days | 7-30 days | >30 days |

## Output

### Attribution Health Score

```
Attribution Health Score: XX/100 (Grade: X)

iOS (AdAttributionKit + ATT):    XX/100  ████████░░  (20%)
Web (GA4 + Ads + CAPI):           XX/100  ██████████  (30%)
Consent Mode V2:                  XX/100  █████████░  (15%)
Server-Side Stitching:            XX/100  ████████░░  (20%)
MMP Health (mobile):              XX/100  ███████░░░  (10%)
Cross-Device / Customer Match:    XX/100  ██████░░░░  (5%)
```

### Deliverables

- `ATTRIBUTION-AUDIT.md`: Full surface-by-surface findings
- Cross-channel attribution map (which platform owns which conversion
  windows + which events)
- Modeled vs reported conversion delta (estimated revenue under- or
  over-attribution)
- Quick Wins sorted by signal-recovery $ impact
- Pre-launch checklist for any new platform (Amazon, Apple Ads, TikTok)
  to ensure attribution is wired before spend begins
