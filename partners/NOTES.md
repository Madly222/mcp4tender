# Partner catalog (feature branch: partners-catalog)

Goal (stages 1-7 all DONE): turn the varied Excel price-lists partners send into one catalog,
then answer "top-3 cheapest partners for this product". Pure code, no AI/RAG — the
join key is BRAND + P/N (MPN). Keyword search on the description is the fallback for
rows with no MPN.

## Isolation / how to remove the whole feature
Almost everything lives under `partners/` and writes only `partner_*` tables.
Two lines in core files wire it in:
  - web/server.py: a try/except include of partners.web.router (safe if the module
    is gone — the except swallows the ImportError).
  - web/user/nav.py: the {"href": "/app/partners", ...} entry in the "Everything" group.
To remove: `git rm -r partners/ tests/test_partners_ingest.py tests/test_partners_web.py`,
delete the nav entry, delete the try/except block in server.py, and drop the
partner_* tables. Nothing else imports partners.

## The idea that tames the format chaos
The engine is generic; each partner's quirks live in ONE small profile. Profiles are
stored in the DB (partner_profiles) and edited through the UI; the code profile in
partners/profiles/accent.py is a built-in default/fallback. Images/banners don't
matter: reading cell VALUES ignores the picture layer. The only real work is locating
the header row and mapping columns — both come from detection + your confirmation.

## The flow (/app/partners)
1. Upload a partner's .xlsx with a partner name.
2. detect.py finds each sheet's header row and PROPOSES a column mapping using an
   EN/RO/RU synonym table; it also guesses which sheets to import.
3. Confirm screen: you fix any wrong column via dropdowns and toggle which sheets to
   import. Detection is a guess (e.g. on Accent it picks promo="акция" instead of
   "promo dealer, usd") — the confirm step is where you correct it.
4. On confirm the mapping is saved as that partner's profile and the file is ingested
   into partner_offers. Next file from the same partner reuses the saved profile.
5. Product pool: paginated, searchable by partner / brand / article / description.

## Data model
partner_files (intake, unique on partner+sha256 so a re-sent file is rejected),
partner_offers (normalized rows: brand, mpn, mpn_norm, description, category_path,
price_original, currency, price_usd, promo_usd, ...), partner_profiles (saved mapping
per partner), partner_staging (an uploaded file awaiting confirmation). Uploaded files
are written to <db-dir>/partner_uploads/.

category_path is built from the sheet's Excel OUTLINE levels (exact hierarchy, e.g.
"PC COMPONENTS / CASE / SHARKOON"), not guessed.

## Canonical profile fields (what the engine understands)
brand, mpn, description, cost (the price WE pay), promo, price_lei, retail_usd,
warranty, stock. Profile: {partner, sheets:[{name, ingest, header_tokens, columns
{field: header-label}, cost_field:"cost", promo_field:"promo", cost_currency,
category:"outline"} | {name, ingest:False, reason}]}. cost_currency!=USD leaves
price_usd NULL for now (wire to suppliers.fx_rates at stage 6).

## Stages
1-4 intake / header detection / profile / normalized catalog — DONE.
5 categorize product-type — DONE (from type, not CPV, per Victor). partners/categorize.py
  TYPE_RULES: ordered (type, keywords, where in path|desc|both); first match wins, so ORDER
  MATTERS (Case Fan must precede the broad CPU-Cooler "|coolers|" rule). Matching is
  delimiter-safe: path is normalized to "|seg|seg|" splitting ONLY on " / " because a segment
  label can contain a literal "/" (e.g. "Case Fan/Fan Control"); path keywords are "|ram|" style,
  desc keywords are plain words. A rule match => type_source="rule" (the reliable cross-partner
  join key). No rule => fall back to the partner's own top category as the type,
  type_source="path" (grouping only works within that partner; shown dimmed in the pool). On
  Accent: 100% typed, 93% by rule. product_type/type_source are columns on partner_offers
  (init_partner_schema migrates them onto old tables via ADD COLUMN). Set at ingest; CLI
  `categorize` re-runs classify on all rows after editing the rules. Pool has a Type filter.
6 supersede old offers on re-ingest + fx for non-USD — DONE (Jul 25). partner_offers.active
  flag (migrated onto old tables): each ingest_workbook sets active=0 on ALL of that partner's
  prior offers then inserts the new file's rows as active=1, so only the latest price-list per
  partner is current; old rows kept for history. The pool, type list, and partner counts all
  filter active=1. FX: partners/fx.py to_usd pivots through MDL (X->USD = X->MDL / USD->MDL)
  reading suppliers.fx_rates from the MAIN project's config (read_fx_rates reads the configs
  table directly; web passes store.get). price_usd is computed for every currency at ingest
  (was USD-only). CLI `fx` backfills price_usd on existing rows. Ranking uses the regular dealer
  cost (price_usd); promo is a note, NOT the ranking price (Victor's call — promo is temporary
  and may lapse by delivery). Identical re-send still rejected by the partner_files sha256 index;
  a CHANGED file supersedes.
7 top-3 cheapest partners per MPN — DONE (Jul 25). partners/rank.py: cheapest_per_partner
  (active offers for an mpn_norm, one row per partner = its lowest regular price_usd, NULLs last),
  top_partners = the 3 lowest; multi_partner_products lists articles carried by >1 partner (the
  sourcing-relevant set) with q/type filters. Ranks by REGULAR dealer price_usd; promo is a shown
  note, never the ranking key. /app/partners/compare: no mpn => the multi-partner list; ?mpn=X =>
  the top-3 table with vs-cheapest deltas and a "saves $ vs next" line. Each pool article links to
  its compare page. All ranking is active=1 only, so a superseded cheaper price never wins.
  Tested end to end with two synthetic partners (real cross-partner proof needs a 2nd real file).

## Dependency
openpyxl (NOT yet used elsewhere server-side — the branch installs it).
python-multipart is already present (used by the settings forms).

## Run without the UI (optional)
    .venv/bin/python -m partners.cli --db tenderengine.db ingest --partner accent <file.xlsx>
    .venv/bin/python -m partners.cli --db tenderengine.db sample -n 10

Accent PriceList_23-10-31.xlsx: 3787 products, 501 category rows, 0 unparsed;
Used-Refurb + ASC skipped.

## Fixes after real partner files (Jul 25)
- LEI-ONLY files silently imported 0 (DKC/Creit): a sheet with only "Pret, MDL" and no dealer/
  cost column was marked ingest=false because the flag required cost or retail_usd. Now detect
  PROMOTES a lone price column into `cost` when no dedicated cost exists (price_lei -> cost,
  cost_currency=MDL; else retail_usd -> USD), the ingest flag needs only mpn + any price, the
  confirm screen preselects the detected currency, and _build_offer falls back cost -> price_lei
  (MDL) -> retail_usd (USD) as a safety net. DKC now imports 173 rows, 124 MDL -> $6.89 @ 18.
- SILENT ZERO fixed: confirm now redirects with a msg banner on the pool — "imported N; M rows had
  no price/article; skipped sheets: ...". No more mystery zero.
- Cross-partner compare needs the SAME article (BRAND+P/N) at 2+ partners; with mostly disjoint
  catalogs the multi-partner list is short. Fuzzy/no-MPN matching is a future task.
