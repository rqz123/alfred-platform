# wa-sim — WhatsApp User Simulator for Alfred

Simulates multiple WhatsApp users sending messages to Alfred without a real phone or WhatsApp account. A fake Bridge server captures Alfred's replies so you can see the full conversation in the terminal.

## How it works

```
Virtual Phones ──→ Gateway webhook (/internal/bridge/messages)
                         │
                    Alfred processes
                         │
                  Fake Bridge (:9001) ←── Gateway sends reply
                         │
                    Terminal UI
```

Setting `BRIDGE_API_URL=http://localhost:9001` in the Gateway's `.env` is all that's needed — no Gateway code changes.

## Setup

```bash
# 1. Point the Gateway at the fake Bridge
echo "BRIDGE_API_URL=http://localhost:9001" >> services/gateway/.env

# 2. Install dependencies
cd wa-sim
pip install -r requirements.txt

# 3. Configure
cp .env.example .env
# Edit .env — set BRIDGE_API_KEY to match the Gateway's BRIDGE_API_KEY
```

### .env options

| Variable | Default | Description |
|---|---|---|
| `GATEWAY_URL` | `http://localhost:8000` | Alfred Gateway address |
| `BRIDGE_API_KEY` | `change-me-bridge-key` | Must match Gateway's `BRIDGE_API_KEY` |
| `BRIDGE_PORT` | `9001` | Port the fake Bridge listens on |
| `SESSION_ID` | `sim-session-001` | Bridge session ID |
| `DB_PATH` | _(empty)_ | Path to Gateway's SQLite DB (for `--auto-register`) |

### First-time: register the Bridge session

The Gateway needs a `WhatsAppConnection` row pointing to `SESSION_ID`. Either create one in the Gateway UI, or use `--auto-register` (requires `DB_PATH`):

```bash
python -m src.main --auto-register --scenario greeting_english
```

## Usage

All commands are run from the `wa-sim/` directory.

### Interactive mode (default)

Type messages and see Alfred's replies in real time. Switch between virtual phones by prefixing with a phone number.

```bash
python -m src.main
```

```
> Hello Alfred
> +18005550002: 明天下午2点提醒我开会
> +18005550001: 花了$40吃午饭
> phones        # list all virtual phones
> quit
```

### Run all scenarios once, group by group

```bash
python -m src.main --auto
```

Runs all 5 phone groups sequentially. Each scenario in every group executes once. Results are written to `output/results.jsonl`.

### Run all groups in parallel (stress test)

```bash
python -m src.main --concurrent
```

All 5 virtual phones run their scenario groups simultaneously — the most realistic test of Alfred's concurrency and fault tolerance.

### Run a specific group

```bash
python -m src.main --group finance
python -m src.main --group reminders
python -m src.main --group notes
python -m src.main --group chat
python -m src.main --group errors
```

### Run a specific scenario

```bash
python -m src.main --scenario add_expense_multiturn
python -m src.main --scenario rapid_fire_messages
python -m src.main --scenario cancel_reminder_by_name
```

### Repeat with random picks

```bash
python -m src.main --auto --loop 5        # 5 random scenarios per group, sequential
python -m src.main --concurrent --loop 3  # 3 random picks per group, all parallel
```

`--loop 0` (default) runs each scenario exactly once.

## Virtual phones

| Phone | Name | Group | What it tests |
|---|---|---|---|
| +18005550001 | Alice | `finance` | add_expense, add_income, get_balance, monthly_report, set_budget |
| +18005550002 | Bob | `reminders` | add_reminder, list_reminders, acknowledge, cancel, get_schedule |
| +18005550003 | Carol | `notes` | add_note, list_notes, search_notes |
| +18005550004 | Dave | `chat` | General conversation, no-intent messages |
| +18005550005 | Eve | `errors` | Gibberish, SQL injection text, rapid-fire, empty messages, unicode edge cases |

## Scenario coverage

**Finance (Alice):** single-turn expense, multi-turn expense (no amount → ask → answer), cancel mid-flow, English expense, mixed-language, income, income multi-turn, balance, monthly report, set budget, MAX\_RETRIES exhaustion.

**Reminders (Bob):** single-turn reminder, multi-turn (title first / time second), English alarm, recurring weekly, tonight reminder, list reminders, acknowledge with ok/好的/yes/收到, cancel by number, cancel by name, get schedule, cancel mid-flow.

**Notes (Carol):** Chinese note, English note, jot trigger, write-down trigger, list notes (Chinese/English), search by Chinese keyword, search by English keyword, empty trigger (should not save).

**Chat (Dave):** English greeting, Chinese greeting, "what can you do?", open question, chat after a finance action, ambiguous short message, long paragraph.

**Errors (Eve):** gibberish, spaces/punctuation only, 500-character message, SQL-injection-looking text, emoji-only, rapid-fire 3 messages, acknowledge with no pending reminder, cancel nonexistent reminder, RTL+LTR unicode, search with no query, cancel-then-fresh-request, service-unavailable simulation.

## Output

| File | Contents |
|---|---|
| `output/results.jsonl` | Every step result (JSON lines) — pass, fail, timeout, send\_error |
| `output/errors.jsonl` | Failures only — subset of results.jsonl for quick scanning |

Each line is a JSON object:

```json
{
  "ts": "2025-04-27T10:30:00.123456+00:00",
  "scenario": "add_expense_multiturn",
  "group": "finance",
  "step": 2,
  "phone": "+18005550001",
  "sent": "15块",
  "reply": "Expense recorded: ¥15.00 (food)",
  "status": "pass",
  "expect_contains": "15",
  "error_detail": ""
}
```

## Adding scenarios

Edit `config/scenarios.yaml`. No code changes needed.

```yaml
- name: my_new_scenario
  group: finance          # assign to Alice's phone group
  weight: 2               # relative pick probability
  description: "What this tests"
  steps:
    - phone: "+18005550001"
      send: "花了$25买书"
      expect_contains: "25"
```

Step options:

| Key | Type | Description |
|---|---|---|
| `phone` | string | Virtual phone number to send from |
| `send` | string | Message text |
| `expect_contains` | string | Substring that must appear in Alfred's reply |
| `no_wait` | bool | Don't wait for a reply (fire-and-forget) |
| `pause` | float | Seconds to pause before this step |
