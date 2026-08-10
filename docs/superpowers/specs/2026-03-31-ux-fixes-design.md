# UX Fixes & Reliability Improvements

**Date:** 2026-03-31
**Scope:** 8 issues identified from real usage logs (3/25–3/31)

---

## 1. Shopping List — Bulk Clear & Better NL Routing

### Problem
No way to clear the grocery list. `grocery_done` only fuzzy-matches one item. NL handler doesn't recognize "clear my shopping list" — user had to ask 4 times with no result.

### Changes

**New command `/grocery_clear`**
- Sets `checked = 1` on all unchecked items in `meals_grocery`
- Responds with count: "Cleared 3 items from your grocery list."
- No confirmation prompt

**NL handler keyword expansion** (meals plugin, priority 10)
- Add keywords: `"clear grocery"`, `"clear shopping"`, `"clear the list"`, `"clear my list"`, `"delete grocery"`, `"empty the list"`, `"done shopping"`, `"check off everything"`
- Route matches containing "clear" or "empty" or "done shopping" to `handle_grocery_clear`

**Files:** `pa/plugins/meals/plugin.py`, `pa/plugins/meals/commands.py`

---

## 2. Email Deduplication

### Problem
Same emails surface across multiple triage windows for days. Experian alerts, PayPal past due, school fees repeated 3-5x.

### Changes

**New table `google_notified_emails`**
```sql
CREATE TABLE IF NOT EXISTS google_notified_emails (
    message_id TEXT PRIMARY KEY,
    subject_snippet TEXT,
    notified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**Filter before triage**
- After fetching unread emails, exclude any `message_id` already in `google_notified_emails`
- Insert message IDs after successful triage notification

**Mark as read in Gmail**
- After successful triage notification, mark the email as read via Gmail API
- The `google_notified_emails` table is the safety net for cases where marking read fails

**TTL cleanup**
- Before each triage run, delete rows from `google_notified_emails` older than 14 days
- Inline prune, no separate job needed

**Files:** `pa/plugins/google/plugin.py`, `pa/plugins/google/gmail.py`, `pa/plugins/google/triage.py`

---

## 3. Kid-Sport Correction Parsing

### Problem
"Asher is the soccer player, not Maddox" didn't match NL handler keywords (`"now plays"`, `"signed up for"`). Fell through to wrong handler which couldn't parse it.

### Changes

**Expand keywords** on kid-sport handler (priority 19)
- Add: `"plays basketball"`, `"plays soccer"`, `"is the soccer"`, `"is the basketball"`, `"not maddox"`, `"not asher"`, `"soccer player"`, `"basketball player"`, `"doesn't play"`, `"is soccer"`, `"is basketball"`

**Smarter parsing in handler**
- Use Claude (Tier.FAST) to extract `{kid, sport}` from any natural phrasing
- Handle corrections like "Asher is soccer, not Maddox" → update both kids
- Prompt: "Extract kid name(s) and sport(s) from this message. Return JSON: [{kid, sport}]. Kids are Maddox (12) and Asher (10)."

**Confirmation response**
- After updating, confirm what changed: "Got it — Asher plays soccer, Maddox plays basketball."

**Files:** `pa/plugins/google/plugin.py`, `pa/plugins/google/handlers.py` (or wherever `handle_kid_sport` lives)

---

## 4. Bart Verbosity

### Problem
Simple factual queries ("what are my debts?") get 200+ word responses with Dumbledore rhetoric, upsells to `/advisor`, and rhetorical questions.

### Changes

**Update Bart/advisor system prompt**
- Add rules:
  - Answer the question asked. Do not upsell other commands.
  - Factual queries (balances, debts, spending totals) get under 80 words.
  - Numbers first, commentary second.
  - No rhetorical questions. No "shall we explore this further?"
  - Save advisory tone for explicit advice requests or `/advisor`.
  - No "consult a professional" — Bart IS the advisor.

**Structured debt response format**
- For debt queries, return tight format:
  ```
  Your debt: $6,557.88

  CreditOne Amex    $2,328.81
  CreditOne Visa    $2,279.75
  Mission Lane      $1,710.82
  AdventHealth        $238.50
  ```
- No follow-up questions unless user asks for a plan

**Files:** `pa/plugins/finance/advisor.py`, `pa/plugins/finance/plugin.py` (system prompt fragment)

---

## 5. Error Display & Token Expiry Handling

### Problem
Raw JSON error blob dumped to Telegram when Teller OAuth expired. Gmail `invalid_grant` shows ugly Python error. No guidance on how to fix.

### Changes

**Human-readable error messages**
- Map known error types to friendly messages in job dispatcher:
  - Teller 401 / OAuth expired → "Bank connection expired. Use `/sync` to reconnect."
  - Gmail `invalid_grant` → "Gmail connection expired. Run `/gmail_auth` to reconnect."
  - Generic API timeout → "Couldn't reach [service]. Will retry next check."
  - Unknown errors → "Something went wrong with [job]. Check logs."

**Suppress repeat error notifications**
- Add `notified_at` column to `core_errors` table
- If same job + same error type was notified in last 24 hours, skip Telegram notification
- Still log to DB for tracking

**Never dump raw JSON/tracebacks**
- Wrap all job error output through a formatter
- Strip JSON payloads, stack traces, request IDs before sending to Telegram
- Log full details to console/DB only

**Files:** `pa/core/scheduler.py`, `pa/plugins/finance/jobs.py`, `pa/plugins/google/jobs.py`

---

## 6. Dinner Nag Suppression

### Problem
"No dinner planned tonight. Want to plan something?" fires every day at 4pm. User never responds. Pure nag.

### Changes

**Track ignored prompts**
- New key in meals state (or `google_state` pattern): `dinner_nag_ignored` (integer count), `dinner_nag_last_engaged` (timestamp)
- After sending dinner prompt, increment `dinner_nag_ignored`
- When user interacts with meals (plans a meal, asks about dinner, adds/clears grocery items), reset `dinner_nag_ignored` to 0 and update `dinner_nag_last_engaged`

**Backoff logic in `job_meal_reminder`**
- If `dinner_nag_ignored >= 3`, stop daily prompts
- Fall back to weekly (Sunday only) until user re-engages
- When user re-engages, resume daily

**Files:** `pa/plugins/meals/jobs.py`, `pa/plugins/meals/commands.py`

---

## 7. Spending Categorization

### Problem
85% of weekly spending in "Uncategorized" and "general." Merchant learning system isn't bootstrapped.

### Changes

**Expand built-in merchant patterns**
- Significantly expand `_KNOWN_MERCHANTS` in `merchants.py` with common US merchants
- Focus on categories that appear in user's actual transactions
- Map variations: "PURCHASE HILLTOP LIQ" → Liquor, "PAYPAL INST XFER" → Transfer, "GLF*SADDLER" → Golf/Recreation

**Auto-categorize on ingest**
- When new transactions arrive from Teller sync, immediately run through:
  1. Learned categories (`finance_merchant_categories`, highest confidence first)
  2. Built-in patterns (`_KNOWN_MERCHANTS`)
  3. If still unknown, queue for batch categorization
- Store category on the transaction row at ingest time

**Batch recategorize command `/recat`**
- Re-runs all uncategorized transactions through matching + Claude fallback
- One-time cleanup for existing backlog
- Reports: "Recategorized 47 transactions. 3 still unknown."

**Claude fallback for unknowns**
- Batch up to 20 uncategorized transaction descriptions
- Ask Claude (Tier.FAST): "Categorize these merchant names into: Groceries, Gas, Food, Liquor, Shopping, Software, Subscriptions, Bills, Transfer, Recreation, Medical, Income, Other"
- Store results in `finance_merchant_categories` with `confidence = 0.5`

**Kill "general" category**
- Replace "general" with specific categories or "Unknown"
- "Other" only for genuinely uncategorizable transactions

**Files:** `pa/plugins/finance/merchants.py`, `pa/plugins/finance/plugin.py`, `pa/plugins/finance/jobs.py`

---

## 8. Email Statement → Debt Extraction

### Problem
Statement emails with balances aren't being pulled into the debt list. Bill scanning runs only in weekly advisor job and may not be extracting reliably.

### Changes

**Improve bill extraction prompt**
- Update Claude prompt in `scan_gmail_for_bills()` to be more aggressive:
  - Extract from any email resembling a statement, collection notice, or past-due alert
  - Required fields: institution, account_name, balance, status
  - Optional fields: due_date, minimum_payment, apr
  - Status values: current, past_due, charged_off, collection

**Trigger extraction during triage**
- During normal email triage (4x daily), if an email is classified as `action` or `important` AND contains financial keywords (statement, balance, past due, minimum payment, amount owed, charged off, collection), flag it for bill extraction
- Run lightweight extraction in the same triage pass
- Upsert results into `finance_debts`

**Verify upsert path**
- Ensure `save_bills_to_db()` correctly upserts into `finance_debts` on `(institution, account_name)` conflict
- Log when a debt balance changes: "Updated CreditOne Visa: $2,279.75 → $2,312.40"

**Files:** `pa/plugins/finance/advisor.py`, `pa/plugins/google/triage.py`, `pa/plugins/finance/plugin.py`
