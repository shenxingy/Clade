# /localize — Full-Site / App Internationalization Playbook

Mission: take a codebase whose UI is hardcoded in one language and ship it in N locales
that render **completely and elegantly** at every viewport, including RTL — verified, not
assumed. Hold the work to MQM / ISO-17100 quality and beat a professional human-translation
vendor on the axes machines win: 100% surface coverage, zero ICU/markup corruption, automated
layout + RTL verification, and term-base consistency across thousands of strings.

This skill is for the **codebase/marketing-site UI** (pages, components, data files, emails).
For translating blog *article content*, use `blog-localize` instead.

---

## The quality bar — how we beat professional translators

A TEP (translate→edit→proofread) vendor delivers fluent strings but does **not** touch your
code, does not guarantee every string is wired, and never tests that German overflows a button
or that Arabic mirrors. We win by owning the whole loop:

1. **Completeness is provable, not sampled.** Every locale's message tree is diffed against the
   source key set — 100% parity or it fails. A vendor proofreads a sample; we verify all 100%.
2. **Zero technical corruption.** ICU placeholders (`{count}`), rich tags (`<strong>`,
   `<br></br>`), and brand/term tokens are preserved byte-for-byte and auto-checked. Vendors
   routinely break these.
3. **Layout is QA'd, not hoped.** Playwright renders every page × locale × viewport and fails on
   horizontal overflow or clipped text. RTL is screenshot-verified. No vendor does this.
4. **One term base.** Brand, product, and acronym handling is a fixed do-not-translate list
   applied identically everywhere — no "Scam AI" vs "ScamAI" drift across 600 strings.
5. **Idiomatic, locale-correct prose** from a strong model with explicit register/locale rules
   (mainland vs Taiwan, pt-BR, MSA, vouvoiement) — then spot-reviewed.

If you cannot verify a claim ("it's translated", "it fits"), you have not done the job. Render it.

---

## Phase 0 — Audit & scope (do this first, always)

1. **Detect the i18n stack.** next-intl, next-i18next, react-i18next, vue-i18n, Angular i18n,
   Lingui, FormatJS. Find the locale config (locale list, default, RTL locales), the message
   files (`src/messages/*.json` or `locales/`), the middleware, and how `<html lang>`/`dir` is set.
2. **Enumerate translatable surfaces** — don't trust "the homepage looks done":
   - Pages/routes (every `[locale]/**/page.tsx` etc.).
   - Shared chrome (nav, footer, cookie banner, command palette, forms).
   - **Data-driven content** in `.ts`/`.json` data files (industry pages, comparison tables,
     pricing tiers) — these are often the *bulk* and are easy to miss.
   - Email templates, `metadata`/SEO, OG-image text, `aria-label`/`alt`/`placeholder`.
3. **Measure current coverage.** `grep -rL "useTranslations\|getTranslations" <component dirs>` —
   files with zero i18n calls are hardcoded. Cross-check by rendering a non-default locale and
   grepping the served HTML for source-language headlines.
4. **Scope by industry benchmark, not "everything at once":**
   - **Translate first (highest ROI):** homepage, pricing, product/feature pages, solutions,
     comparison pages, nav/footer, signup/contact forms.
   - **Then:** docs, resources, about/company.
   - **Optional / later:** blog content (high volume, low per-page ROI — often English or
     selectively localized even at Stripe-scale).
   - **Keep English (or use a certified legal translator):** terms, privacy, cookies, MSA, EULA.
     Machine-translating legal text is a compliance liability; top SaaS vendors do not do it.
   - **Language set:** Stripe localizes ~15 languages; typical strong B2B coverage is 8–15. Pick
     by addressable market, not by what's easy. Confirm the set with the user before mass work.
5. **A visible language switcher is part of "offering translation."** If the site has translations
   but no switcher (or one that's dead code / lists a subset of locales), users can't reach them.
   Adding/fixing it is in scope (see Phase 3).

Decide scope with the user when it involves **scale** (huge data files, blog) or **liability**
(legal). Don't ask about small mechanical things — just do them.

---

## Phase 1 — Extract source strings & wire i18n

Run **parallel agents, one per component/page group** (disjoint files → no write conflicts).
Each agent OWNS its files, and **returns the English namespace as JSON** — it does NOT edit the
shared message file (concurrent writes to `en.json` corrupt or clobber each other).

Each agent's contract:
- Add `useTranslations("<namespace>")` (client) / `getTranslations` (server). Replace ONLY
  user-visible text (headings, body, button/link labels, `aria-label`, `alt`, `title`,
  `placeholder`). Never touch: URLs/`href`, `className`, SVG paths, analytics event names,
  `data-*`, ids, computed numbers/prices.
- **Module-level data arrays** (nav items, FAQs, pricing add-ons, comparison rows): keep a stable
  `key`/`id` per item; store text in the namespace keyed by that id; resolve via `t()` at render.
  `t()` is not available at module scope.
- **Data-file → namespace pattern** (for `industries.ts`-style files): strip the data file to
  structural-only fields (`slug`, booleans, numeric stat values, icons, hrefs, array *counts*);
  move all prose into `<namespace>.<slug>.<field>`; the page iterates `Array.from({length: count})`
  and resolves `t(\`<slug>.section.${i}.title\`)`. Update `generateMetadata`/JSON-LD/OG-image to
  resolve from the namespace too.
- **Rich / inline-markup strings:** prefer splitting into segments that keep the JSX/styling
  (`<>{t("a")}<br/>{t("b")} <span className="x">{t("hl")}</span></>`), OR `t.rich("key", { strong:
  c => <strong className="x">{c}</strong> })`. Never drop a className.
- **Normalize the brand** in extracted text to the canonical form (e.g. "Scam AI", not "ScamAI"),
  but leave the logo wordmark, domains, emails, and social handles literal.
- Use a **typographic apostrophe `’` (U+2019), never a straight `'`** in any extracted English
  value with an apostrophe (see ICU landmine below).
- Output a single ```json block `{ "<namespace>": {...} }` whose keys EXACTLY match the `t()`
  calls written. Don't run build/git.

You then **merge all returned namespaces centrally** into the source-locale file (text-insert as
the first top-level key to keep diffs minimal), and **build + leak-scan the source locale first**
— if EN is clean, only then translate. Non-source locales fall back to source text until merged,
so the site never crashes mid-migration.

---

## Phase 2 — Translate

Extract the merged source namespace to a single `/tmp/<source>.json`, then run **parallel agents,
one per 1–2 locales**, each reading that file and **writing `/tmp/<locale>.json`** (agents write
/tmp, never the repo — you merge centrally).

Hard rules every translation agent gets:
- **PRESERVE EXACTLY (do not translate):** brand & product names; model/SKU names; proper nouns
  (companies, people, places); competitor names; tech acronyms (API, REST, SDK, SLA, KYC, GDPR,
  SOC 2, GAN, GenAI, RTL…); file formats; numbers, percentages, prices, currency; URLs, domains,
  emails; the source's quoted paper/citation titles. Provide this as an explicit list per project.
- **KEEP ICU placeholders verbatim** (`{count} {price} {name}`) — same braces, same variable name.
- **KEEP rich tags exactly**, translate only the text *inside* them: `<em></em> <strong></strong>
  <highlight></highlight> <link></link> <br></br>`. Tag must be paired (`<br></br>`, not `<br>`).
- **Typographic apostrophe `’` only — NEVER a straight `'`.** Critical for French (l’, d’, n’,
  qu’) and any romance language; a straight `'` truncates the string at render (see landmine).
- Idiomatic, register-correct, market-correct prose: zh-CN mainland vs zh-TW Taiwan conventions,
  pt-BR, neutral es, MSA Arabic, fr vouvoiement, German compound length. "Yes/No/Limited" data
  cells → natural target words.
- Output must have the EXACT same key structure as the source (every leaf, none added/removed).

Agents that hit a usage/rate limit may have **already written their files** before the error —
check `/tmp` before re-spawning. For any locale an agent couldn't finish, translate it yourself.

---

## Phase 3 — Integrate

1. **Validate every locale file** against the source key set BEFORE merging (script below). Fail on
   missing/extra keys, lost ICU placeholders, tag-count mismatch, or any straight apostrophe.
2. **Merge** each locale's namespaces into its message file. Convert any straight apostrophes to
   `’` as a final safety pass.
3. **`<html lang>` / `dir`:** derive from the framework's request locale (next-intl: `await
   getLocale()` in the root layout), NOT from a cookie the middleware writes — see landmine.
   RTL locales get `dir="rtl"`.
4. **Static rendering:** next-intl needs `setRequestLocale(locale)` in the `[locale]` layout AND
   every statically-rendered page; load messages via `getMessages()` (single source of truth),
   not a hand-rolled second import.
5. **Visible language switcher:** desktop dropdown + mobile list, **all** locales, each labelled
   in its own language, current locale marked, **path-preserving** (next-intl:
   `router.replace(pathname, { locale })`). Localize its `aria-label`.

---

## Phase 4 — Verify (this is where you beat the vendor)

1. **Key parity (every locale):** leaf-key set == source. 0 missing / 0 extra.
2. **Type + build:** `tsc --noEmit` clean; production build succeeds with no `IntlError` /
   `MISSING_MESSAGE`.
3. **Leak scan (rendered HTML):** for each translated page × a few locales, grep the served HTML
   for `namespace.key` patterns — any hit is an unresolved key (missing key or broken `t.rich`
   tag) and must be 0. (Component `t()` calls can reference keys the agent forgot to return — this
   catches them; it also catches `<br>`-not-`<br></br>` tag failures.)
4. **UI viewport + RTL audit (Playwright):** render every page × {longest locale (de), RTL (ar),
   CJK (ja/zh), baseline (en)} × {mobile 375, laptop 1024, desktop 1366}. FAIL on:
   - horizontal overflow (`document.documentElement.scrollWidth > innerWidth`),
   - clipped text (`scrollWidth > clientWidth` on `overflow:hidden`/`nowrap`/`ellipsis` text nodes).
   Screenshot the extremes (longest-on-smallest, RTL, dense tables) and **actually look at them**.
   Note: below-fold sections often use scroll-reveal (`opacity:0` until in-view); a static element
   screenshot shows them empty — scroll the page first (`mouse.wheel` loop), then assert
   `getComputedStyle(row).opacity === "1"` before concluding anything is broken.

### Validation script (drop-in)
```js
const fs=require("fs"); const en=JSON.parse(fs.readFileSync(SRC));
const paths=o=>{const r=[];(function w(x,p){for(const k in x){const q=p?p+"."+k:k;
  x[k]&&typeof x[k]==="object"?w(x[k],q):r.push(q)}})(o,"");return r};
const E=new Set(paths(en)), ICU=/\{[a-zA-Z]+\}/g, TAG=/<\/?[a-z]+>?/g;
for(const loc of LOCALES){const d=JSON.parse(fs.readFileSync(`/tmp/${loc}.json`));
  const L=new Set(paths(d)); const miss=[...E].filter(x=>!L.has(x)), extra=[...L].filter(x=>!E.has(x));
  // also walk leaves: ICU set + tag multiset must match source per key; no straight "'"
  console.log(loc, L.size+"/"+E.size, miss.length?("MISS "+miss.slice(0,5)):"", extra.length?("EXTRA"):""); }
```

---

## Landmines (hard-won — each one cost real time)

- **ICU straight-apostrophe truncation.** In ICU MessageFormat (`t.rich` especially), a straight
  `'` can start a quoted section and silently drop the rest of the string at render. Symptom:
  text appears cut off after the apostrophe. Fix: use `’` (U+2019) in all message values; convert
  on merge. French breaks the most.
- **Stale `next start` testing trap.** `kill -9; sleep 1; next start -p PORT` often leaves the old
  process bound (`EADDRINUSE`); the new server dies and you curl/screenshot the OLD build. Cost a
  multi-hour false "framework bug" hunt once. ALWAYS: kill, `sleep 3`, assert `[ -z "$(lsof
  -ti:PORT)" ]`, use a FRESH port per rebuild, grep the server log for `EADDRINUSE`, and bake a
  unique marker into the page to confirm freshness before trusting any result.
- **Next.js build cache serves stale components.** If a component edit isn't reflected, `rm -rf
  .next` (and `node_modules/.cache`) and rebuild. Server components recompile more reliably than
  client ones under incremental builds.
- **next-intl SSG drops the locale.** Without `setRequestLocale`, statically-prerendered routes
  can resolve to the default locale and render source text for *some* locales. Add it in layout +
  page; use `getMessages()`.
- **Metadata objects REPLACE, not deep-merge.** A page setting `openGraph: { title }` drops the
  parent layout's `openGraph.url/locale/images`. Provide the complete object or don't override.
- **`<br>` must be `<br></br>`** (paired) for next-intl `t.rich`; a bare `<br>` fails to parse and
  the whole string renders as the key.
- **`<html lang>` from a cookie is wrong for SSG.** The cookie is written one request late and is
  absent at build; derive lang/dir from the route locale instead. (RTL silently stays `ltr`.)
- **Don't blanket-replace a brand string.** `ScamAI → Scam AI` must skip domains (`scam.ai`),
  social handles (`@ScamAI_Official`), file names, and code identifiers — use a negative-lookahead
  (`/ScamAI(?![A-Za-z0-9_])/`) and verify with tsc + a build.
- **Agents told "don't edit the shared JSON" sometimes do anyway** — and concurrent writers can
  clobber. Have them RETURN JSON; you merge. Always re-validate the merged file parses.

---

## Output

Commit in reviewable units (extraction/wiring, per-wave translations, switcher, lang/dir fix).
On `main` that auto-deploys, confirm before pushing if the user hasn't pre-authorized. Report:
locales shipped, surfaces covered vs deferred (legal/blog), key counts, and the audit results
(overflow/clip/RTL = pass). Record any project-specific term base and gotchas to memory.
