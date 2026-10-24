# Blinks Bright — AI clinic chatbot

An AI sales assistant and back office for **Blinks Bright**, a simulated skin and
aesthetic clinic. Customers browse the clinic's site, chat with the assistant, book a
slot and pay a deposit; staff watch every conversation, take over when needed, and run
bookings, payments, CRM and follow-ups from one console.

Final project for **06048308 Intelligent Chatbot Development**. Every clinic, doctor,
price and customer in the seed is **invented data** — see
[docs/PROJECT_BRIEF.md](docs/PROJECT_BRIEF.md).

![Customer site with the AI chat open](docs/screenshots/home-chat.jpeg)

The platform underneath is one FastAPI app that can host several fully isolated
clinics. This repository ships one, Blinks Bright.

### Course deliverables

| Deliverable | File |
|---|---|
| Business, target customers, background, 10 FAQ, bot must / must-not | [docs/PROJECT_BRIEF.md](docs/PROJECT_BRIEF.md) |
| Test record: 10 questions, 5 images, 5 safety cases (real runs, answers, pass/fail, response time) | [docs/TEST_RESULTS.md](docs/TEST_RESULTS.md) |
| 3 improvements with before/after evidence | [docs/IMPROVEMENTS.md](docs/IMPROVEMENTS.md) |
| Architecture diagram + data flow of one message | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| Requirement gap analysis, MVP scope, user journey | [docs/GAP_ANALYSIS.md](docs/GAP_ANALYSIS.md) |
| Demo clip script (≤ 3 min) | [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md) |
| Pair roles and progress log | [docs/TEAM_LOG.md](docs/TEAM_LOG.md) |

---

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env          # add OPENAI_API_KEY (Gemini key is optional)
python run.py                 # creates and seeds clinic.db, serves on :8051
```

| Page | URL | Sign-in |
|---|---|---|
| Customer site | `http://localhost:8051` | none |
| Customer portal | `http://localhost:8051/portal` | phone + password |
| Chat widget on its own | `http://localhost:8051/chat/blinks-bright` | none |
| Staff console | `http://localhost:8051/admin` | email + password |

The server reads `.env` once at startup, so restart it after changing a key. An
`OPENAI_API_KEY` set as an ordinary environment variable works too. Without it the
assistant answers every message with a fixed fallback line.

Tested with Python 3.11 on Windows 11. No other service is required: the database is a
single SQLite file (`clinic.db`, created on first run; delete it to reseed).

### Demo login

**Staff** sign in at `/admin` as the clinic owner:

| Email | Password | Lands on |
|---|---|---|
| `owner@blinksb.co` | `demo1234` | Blinks Bright, all branches, every screen (opens on **Conversations**) |

**Customers** have no seeded logins. Register at `/portal` with a phone number and a
password of at least 8 characters. Registering with a phone number that a demo customer
already holds claims that record, so their bookings show up.

---

## Customer side

### Clinic site

The public landing page: treatments, promotions, doctors, branches and opening hours,
all read live from the clinic's catalog. It switches between Thai and English, and the
chat bubble opens the assistant on any section.

| | |
|---|---|
| **Home**<br>![Home](docs/screenshots/home-hero.jpeg) | **English**<br>![Home in English](docs/screenshots/home-english.jpeg) |
| **Promotions**<br>![Promotions](docs/screenshots/home-promos.jpeg) | **Treatments**<br>![Treatments](docs/screenshots/home-services.jpeg) |
| **Doctors**<br>![Doctors](docs/screenshots/home-doctors.jpeg) | **Branches and hours**<br>![Branches](docs/screenshots/home-branches.jpeg) |
| **Sign-up call to action and footer**<br>![Footer](docs/screenshots/home-footer.jpeg) | |

### AI chat

The assistant answers from the clinic's knowledge base, checks real availability, books
the appointment and shows the clinic's PromptPay QR with the amount due. Replies stream in
as they are written.
The button in the header starts a new chat.

| Greeting and quick replies | Payment QR with the hold countdown | Slip sent: hold paused for staff |
|---|---|---|
| <img src="docs/screenshots/chat-widget.jpeg" alt="Chat widget" width="280"> | <img src="docs/screenshots/chat-qr.jpeg" alt="Payment QR in chat" width="280"> | <img src="docs/screenshots/chat-slip.jpeg" alt="Slip received in chat" width="280"> |

Payment is by the clinic's PromptPay QR. When the customer sends a transfer slip, the
hold on their slot pauses and they are told the team is checking it; staff confirm it on
**Payments** (or reject it, which restarts the hold), and the customer then receives the
booking confirmation. Any other photo is answered by the assistant as usual.

### Customer portal

Sign up or sign in with a phone number, then see the next appointment, booking history,
payment history and profile. The chat here continues the customer's own thread.

| | |
|---|---|
| **Sign in / sign up**<br>![Portal sign-in](docs/screenshots/portal-signin.jpeg) | **My account**<br>![Portal account](docs/screenshots/portal-account.jpeg) |

---

## Staff console

Signed in as the owner, the menu has **8 screens** for the final-project scope:

| | |
|---|---|
| **Sign in**<br>![Login](docs/screenshots/login.jpeg) | **Conversations** — every web chat in one inbox, customer photos and slips, AI source chips and human takeover<br>![Conversations](docs/screenshots/conversations.jpeg) |
| **Bookings**<br>![Bookings](docs/screenshots/bookings.jpeg) | **Doctors and staff**<br>![Team](docs/screenshots/team.jpeg) |
| **Customers** — list, pipeline and profiles<br>![Customers](docs/screenshots/customers.jpeg) | **Payments** — slips waiting for review, confirm or reject<br>![Payments](docs/screenshots/payments.jpeg) |
| **Treatments** — the menu the AI sells and prices from<br>![Treatments](docs/screenshots/treatments.jpeg) | **Knowledge base**<br>![Knowledge base](docs/screenshots/knowledge.jpeg) |
| **Settings** — branches, hours, team, AI instructions<br>![Settings](docs/screenshots/settings.jpeg) | |

Six screens are **hidden from the menu** because the brief does not ask for them: the
overview dashboard, the Test console (a developer tool; the course test record comes from
`evals/deliverable.py`), Retention, AI analytics, Chat analysis and Broadcast. Their
screens and APIs are still in the code (`tests/` still calls `/api/test/*`), and opening a
hidden screen's URL lands on the home screen instead. Un-comment its line in `NAV` in
`web/js/app.js` to bring one back.

---

## What the assistant does

| Area | Behaviour |
|---|---|
| **Grounded answers** | Retrieves from the clinic's own treatments, promotions, branches, doctors and articles. A guard flags any price or number in a reply that is not in the retrieved context or a tool result. |
| **Tools** | Search the knowledge base, list treatments and promotions, check availability, book, reschedule, show the payment QR, ask for human help. |
| **Booking flow** | Collects branch, treatment, date and time, name and phone one at a time, summarises once, then asks deposit or full payment before booking. |
| **Slot holds** | An unpaid booking holds its slot for 10 minutes, then releases it and tells the customer. |
| **Branch-aware** | Prices, treatments and opening hours can differ per branch; the assistant only offers branches that have what the customer asked for. |
| **Language** | Replies in the customer's language (Thai or English), decided from their own messages. |
| **Memory** | Recent messages, the customer's CRM profile, a running conversation summary and their booking history. |
| **CRM capture** | Extracts name, phone, email, interest and budget from the chat into the customer record. |
| **Human takeover** | Staff can take over a conversation; the assistant pauses, then resumes with the teammate's messages as context. |
| **Images** | Customers can send a photo (a payment slip, a price tag, a skin photo) and the assistant responds to it. |

## Tech stack

- **Backend** — Python, FastAPI, SQLAlchemy 2.0, SQLite
- **Frontend** — vanilla JavaScript (ES modules, no build step), CSS, custom SVG charts
- **AI** — OpenAI `gpt-5.6-luna` for chat with streamed tool calling, `text-embedding-3-small` for retrieval over embeddings stored in SQLite
- **Payments** — the clinic's PromptPay QR; staff confirm each transfer from the slip
- **Realtime** — WebSocket, isolated per clinic
- **Channel** — the web chat widget

## Real and simulated

- **Web chat** is fully real.
- **Payments** are by bank transfer to the clinic's PromptPay QR
  (`web/assets/images/payment-qr.png`). The QR in this repository is a **mock** (Demo
  Bank, test data): it cannot receive money. The customer sends the slip in chat and a staff
  member confirms it on Payments → ยืนยันรับเงิน, which confirms the booking and tells the
  customer. Nothing checks the slip automatically.
- **Clinic data** — branches, treatments, prices, doctors, customers — is all simulated.

## Tests and evals

```bash
python -m pytest tests/                 # offline regression suite, throwaway database
python -m evals.deliverable             # the course test record: 20 cases, real model
PYTHONPATH=. python -m evals.run        # AI-quality harness; calls the real model
```

`evals.deliverable` sends the 10 questions, 5 test images and 5 safety cases through the
chat widget's own endpoints on a throwaway copy of Blinks Bright, grades each reply
against criteria fixed in the code, and rewrites `docs/TEST_RESULTS.md`. Options:
`--only=Q1,S2` runs some cases, `--sample=I4:5:tag` repeats one case for before/after
evidence, `--regrade=<json>` re-grades stored replies without calling the model. On
Windows set `PYTHONIOENCODING=utf-8` so the Thai progress lines print.

The evals spend real OpenAI tokens and are not deterministic. They measure reply
quality; they are not a pass/fail gate.

## Project layout

```
app/        FastAPI backend
  ai/         orchestrator, prompts, RAG, memory, tools, guards
  routers/    one router per domain (portal = the customer API)
  services/   booking, inbox, automations, scheduler, billing + payment QR
  seed_main.py  the Blinks Bright seed data
web/        home.html     customer site
            portal.html   customer portal
            chat.html     chat widget
            index.html    staff console shell (served at /admin)
            css/, js/views/
tests/      pytest regression suite
evals/      AI-quality harness + deliverable.py (the course test record)
docs/       course deliverables, test images, evidence, screenshots
run.py      launcher (port 8051)
```

## A two-minute tour

1. Open `http://localhost:8051`, click the chat bubble and ask about a treatment and
   its price.
2. Pick a branch, a date and a time, give a name and phone number, and choose deposit.
   The assistant books the slot and shows the PromptPay QR with the amount due.
3. Sign in at `/admin` as `owner@blinksb.co`. The conversation is in **Conversations**,
   with the customer's details filled in from the chat.
4. Click **Take over** (รับช่วงดูแลเอง) to reply as a person, then hand the chat back
   to the assistant.
5. Open **Bookings** and **Payments** to see the appointment and its deposit.
6. Register at `/portal` with the same phone number to see that booking from the
   customer's side.
