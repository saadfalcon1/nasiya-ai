# Nasiya AI — the AI manager for neighborhood shops

> Built for the **Meta Global AI Developer Hackathon** (Oct 26 – Nov 4, 2026) · Track: *Build for Your World*
>
> **Live bot:** [@nasiyadev_bot](https://t.me/nasiyadev_bot) — press `/start`, then `/demo`

In Uzbekistan, millions of people buy groceries on credit (*nasiya*) at the corner shop every day.
That credit lives in a paper notebook: entries get lost, customers dispute amounts, the shopkeeper
forgets who promised to pay when, and nobody knows whether the shop actually makes a profit.

**Nasiya AI** lets the shopkeeper keep doing what they already do — just *say it* in Uzbek:

> 🎤 *"Akmal aka ikki kilo shakar bilan bitta non oldi, nasiyaga yozib qo'y"*
> ("Akmal took two kilos of sugar and a loaf of bread — put it on credit")

…and gives them a ledger, a two-sided record their customers can verify, and a manager
that tells them every morning what to do.

## What it does

| | |
|---|---|
| 🗣 **Speak, don't type** | Credit, payments, cash sales, deliveries, promises — in natural Uzbek |
| 🤔 **Asks instead of guessing** | "Which Akmal?" (buttons) · "Price of sugar?" · reuses last known price |
| ✅ **Confirm before saving** | Every entry shows a card: items, total, balance *before → after*, limit warnings |
| 🤝 **Two-sided ledger** | Customer links via a Telegram deep link, sees every entry and taps ✅ / ❌. Disputes alert the shop instantly |
| 📅 **Promise tracking** | "Akmal aka juma kuni beraman dedi" ("Akmal said he'll pay on Friday") → reminder on Friday; marked kept when paid |
| 🔔 **Automatic reminders** | Daily, on the promise date or after 14 days without payment, max once per 3 days — via Telegram. Customers link themselves once by sharing their phone number; the bot matches it to the shop's records |
| 📸 **Shelf audit from a photo** | Snap the shelf → the model counts items, flags what is running low, missing, or not in the books. Morning vs evening photo minus recorded sales = **unrecorded sales / shrinkage**, in so'm |
| 📊 **Reports** | Daily / weekly / monthly revenue, cash vs credit, estimated profit, outstanding credit, trends |
| 🧠 **Shop manager** | Data-driven tips: what runs out in 3 days and how much to order, dead stock freezing cash, products sold at a loss, customers who haven't paid in 30+ days, broken promises |
| ☀️ **Morning brief** | Sent automatically every day with one-tap reminder buttons |
| 🛡 **Credit limits** | "Akmal akaga limit 500 ming" ("limit for Akmal: 500,000") → warning when a new entry would exceed it |

**Design principle — never guess with someone's money.** A partial name match is never auto-linked
to an existing customer, prices are never invented, and every entry keeps the original sentence or
transcript for audit.

## Languages: Uzbek, Russian, English

Everything is fully trilingual: bot messages, confirmation cards, reports, morning brief, reminders and the Mini App.
- The language is chosen at `/start` (auto-suggested from Telegram), and can be changed with `/lang` (`/til`), or with the 🌐 button in the Mini App.
- Shop owner and each customer have **their own** language: a Russian-speaking shopkeeper can send reminders that arrive in Uzbek to an Uzbek-speaking customer.
- Commands: Uzbek `/bugun /qarzlar /ombor…`, Russian/English `/today /debts /stock…` (both always work).
- Input can be in any of the three languages (or mixed) — the AI parses it. All strings live in `shop/i18n.py`; a test checks every key has all 3 languages with identical placeholders.

## Telegram Mini App

The bot is for **input** (voice is faster than any form); the Mini App is for **seeing**:

- **Home** — revenue (cash vs credit), cash collected, estimated profit, outstanding credit, 14/30-day chart,
  promises due today, manager tips, top products
- **Debtors** — search and sort (amount / overdue / promises); customer card with balance, credit-limit meter,
  one-tap reminder preview & send, share link to connect, phone & limit settings, full history
- **Stock** — days left per product, dead stock and frozen cash, products sold at a loss, margins
- **History** — every entry with source (🎤 voice / 📷 photo), filters
- **Customer view** — the same app, opened by a customer, shows *their* balance and lets them confirm ✅ or
  dispute ❌ each entry

Every API call is authenticated with Telegram `initData` (HMAC-SHA256 with the bot token); customers can only
see their own records, shops only their own customers.

## Architecture

```
Telegram (voice / text / photo)            Customer's Telegram
        ↓                                         ↑   ✅ / ❌
   Muse model → structured JSON              notices, reminders
        ↓                                         │
   Verification (which customer? price?)          │
        ↓                                         │
   Confirmation card ──► Django + DB ─────────────┘
                            │
                ┌───────────┼─────────────┐
           reports.py   insights      morning brief (scheduler)
```

| Meta model | Used for | How |
|---|---|---|
| **Muse Spark Open** (open weights) | All the intelligence: Uzbek/Russian/English text → structured ledger entry, dates, names, promises; Q&A; invoice photos | Fireworks (OpenAI-compatible API, `AI_BACKEND=open`); Baseten / Modal also supported |
| Muse (Meta Model API) | Same, via Responses API | `AI_BACKEND=meta` (needs an API key) |
| Muse Spark Open (vision) | Shelf photo → item counts → shrinkage detection | ✅ `shop/shelf.py` |
| **Meta MMS** (open weights) | Uzbek voice notes → text | runs on our server, CPU (`shop/ai/stt.py`) |
| Muse Voice Transcribe | Russian/English voice → text (alternative) | Meta Model API `/v1/asr/transcribe` |

**Voice → text, Meta-only:** Muse Spark Open accepts text and images, not audio. Voice notes are transcribed on our own server by **Meta MMS** (`facebook/mms-1b-all`, open weights, 1,100+ languages incl. Uzbek; `STT_BACKEND=mms`), or by **Muse Voice Transcribe** on the Meta Model API (`STT_BACKEND=meta`, for Russian/English). Then every decision is made by Muse Spark Open. Every model called at runtime is a Meta model.

The AI layer is swappable (`shop/ai/`): `mock` (offline rule-based parser for tests), `open`, `meta`.
Run `python check_llm.py [voice.ogg]` to verify a model endpoint.

## Try it in 30 seconds

Open [@nasiyadev_bot](https://t.me/nasiyadev_bot) → `/start` → choose English → `/demo` loads a realistic 30-day shop history.
Then try `/brief`, `/tips`, `/week`, `/debts`, tap **📊 Shop** for the Mini App, send a voice note or a shelf photo,
or just write *"Akmal took 2 breads on credit"*.

## Run locally

```bash
python -m venv venv
venv\Scripts\activate            # Windows   (Linux/Mac: source venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env           # fill TELEGRAM_BOT_TOKEN   (Linux/Mac: cp)
python manage.py migrate
python manage.py runbot
```

`AI_BACKEND=mock` runs without an API key (rule-based Uzbek parser for development and tests).
Set `AI_BACKEND=open` + `LLM_API_KEY` (Fireworks, Muse Spark Open) — this is what the live bot uses —
or `AI_BACKEND=meta` + `MODEL_API_KEY` for the Meta Model API. Voice: `STT_BACKEND=mms` (needs ~4 GB RAM). `SMS_BACKEND=console` logs SMS
instead of sending; `eskiz` sends real SMS via Eskiz.uz.

Mini App in a browser without Telegram (development only): set `DJANGO_DEBUG=1` and
`WEBAPP_DEV_USER=<your Telegram id>`, run `python manage.py runserver`, open http://127.0.0.1:8000/app/
(`?theme=dark` for dark mode). In Telegram the Mini App needs HTTPS — set `WEBAPP_URL` and the bot adds a
menu button automatically.

Tests: `python manage.py test shop` (62 tests)

## Deploy (Ubuntu 22.04/24.04)

```bash
git clone https://github.com/<you>/nasiya-ai.git /opt/nasiya_ai
sudo bash /opt/nasiya_ai/deploy/setup.sh     # PostgreSQL, gunicorn, Caddy (auto-HTTPS), systemd
```
Updates: `sudo bash /opt/nasiya_ai/deploy/update.sh`. A step-by-step setup guide in Uzbek is in `QOLLANMA.md`.

## Project structure

```
shop/
  models.py      Shop, Customer, Product, Transaction, Promise, MessageLog, PendingAction
  services.py    business logic: resolve customer, prices, confirm, balances, two-sided ledger
  reports.py     summaries, profit, stock velocity, insights, morning brief
  notify.py      reminder drafting, automatic Telegram reminders, SMS (Eskiz.uz)
  bot.py         Telegram bot (aiogram 3): shopkeeper + customer roles, scheduler
  api.py         Mini App JSON API + initData verification
  templates/shop/app.html   Mini App (single file, no build step, follows Telegram theme)
  demo.py        /demo — realistic 30-day shop history
  dates.py, nlp.py   Uzbek dates ("juma kuni" = on Friday, "15-noyabrda" = on Nov 15) and numbers
                     ("bir million ikki yuz ming" = 1,200,000)
  shelf.py       shelf-photo audit: counts vs. stock vs. recorded sales -> shrinkage
  i18n.py        all user-facing text in Uzbek / Russian / English
  ai/
    prompts.py        system prompts
    openai_compat.py  Muse Spark Open via OpenAI-compatible API (Fireworks / Baseten / Modal)
    meta.py           Meta Model API client (Responses API)
    stt.py            speech-to-text: Meta MMS (on-server) or Muse Voice Transcribe
    mock.py           offline rule-based parser for tests
deploy/          setup.sh / update.sh — one-command Ubuntu deployment
check_llm.py     smoke test for the model endpoint (text, voice, photo)
```

## Built during the hackathon

All code in this repository was written from scratch during the hackathon building period (Oct 27 – Nov 4, 2026):
the Telegram bot, the Mini App, the AI layer (Muse Spark Open + Meta MMS), the two-sided ledger, shelf audit,
reports and manager insights, automatic reminders, three languages, tests and the deployment scripts.