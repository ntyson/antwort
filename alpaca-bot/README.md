# Alpaca Day-Trading Bot

Autonomous stock day trader for [Alpaca](https://alpaca.markets/) paper (default) or live accounts.

Inspired by agent-style loops that scan on a timer, trade only when the edge is wide enough, size by conviction, and **change behavior under drawdown** (survival mode) instead of averaging down into a hole.

> No bot can guarantee the highest return. This one optimizes for high-conviction intraday momentum/VWAP/breakout edges with hard loss limits. Past or synthetic backtests are not predictive.

## What it does every cycle

1. Confirms the US equity session is open  
2. Syncs **normal / survival / halted** mode from day drawdown, peak giveback, or bleeding positions  
3. Manages exits (signal sells, survival cuts, EOD flatten)  
4. Pulls bars for the watchlist and runs four strategies  
5. Keeps only setups above the conviction threshold  
6. Sizes by risk × score (wider edge → larger size)  
7. Submits bracket orders (entry + stop + take-profit)  
8. Logs every risk decision and fill to SQLite  

### Survival mode (tweet-style adaptation)

Survival mode triggers when **any** of these fire:

- Day drawdown ≥ `SURVIVAL_DRAWDOWN_PCT` (default 2%)
- Giveback from intraday equity peak ≥ `SURVIVAL_GIVEBACK_PCT` (default 0.5%)
- Any open position down ≥ `SURVIVAL_POSITION_LOSS_PCT` (default 1.5%)

Then the bot:

- **Stays in survival for the rest of the session** once triggered (no flip-flop back to normal)
- Drops mean-reversion  
- Raises the minimum signal score  
- Trims position size and max concurrent names (still deploys into best setups)  
- Cuts open losers at `SURVIVAL_POSITION_CUT_PCT` (default 1%) instead of waiting for 2%  

If daily or weekly loss limits trip → **halt** (no new entries).

## Strategies

| Name | Idea |
|------|------|
| `momentum` | EMA stack + MACD + RSI |
| `vwap` | Intraday VWAP reclaim / hold |
| `breakout` | 20-bar high + volume expansion |
| `mean_reversion` | Lower Bollinger + RSI (disabled in survival) |

## Quick start

```bash
cd alpaca-bot
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install -e .

cp .env.example .env
# Edit .env with paper keys from:
# https://app.alpaca.markets/paper/dashboard/overview
```

```bash
python -m alpaca_bot status      # account + positions
python -m alpaca_bot once        # one scan/trade cycle
python -m alpaca_bot run         # autonomous loop (default every 60s)
python -m alpaca_bot backtest    # synthetic smoke backtest
python -m alpaca_bot flatten     # close everything
```

## Deploy on Railway (no local computer)

Yes — Railway can host this as a long-running **worker** (not a website).

The failed GitHub check `focused-appreciation - antwort` was **Railway’s deploy**, not unit tests.

1. Open [railway.app](https://railway.app) → your project → the **antwort** service
2. **Settings → Root Directory:** set to `alpaca-bot` (recommended)  
   If you leave it blank, the repo-root `Dockerfile` also builds this bot.
3. **Variables** (required — deploy fails/idles without them):

| Variable | Value |
|----------|--------|
| `ALPACA_API_KEY` | your paper key |
| `ALPACA_SECRET_KEY` | your paper secret |
| `ALPACA_PAPER` | `true` |

4. **Settings → Deploy:** start command should be `python -m alpaca_bot run` (Dockerfile already sets this)
5. Turn **off** any custom health check path other than `/health`, or leave Railway’s default — the bot serves `GET /health` on `$PORT`
6. Redeploy. Logs should show cycle summaries every ~60s (or `market closed` outside US hours)

Check trades in the [Alpaca paper dashboard](https://app.alpaca.markets/paper/dashboard/overview).

**Billing note:** use a Railway plan that keeps the service awake 24/7.

### Local Docker (same image Railway uses)

```bash
cd alpaca-bot
docker build -t alpaca-bot .
docker run -e PORT=8080 --env-file .env alpaca-bot
```

## Configuration

| Env var | Default | Meaning |
|---------|---------|---------|
| `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` | — | Required |
| `ALPACA_PAPER` | `true` | Paper vs live |
| `RISK_PROFILE` | `aggressive` | `conservative` / `moderate` / `aggressive` |
| `LOOP_INTERVAL_SECONDS` | `60` | Cycle period |
| `STRATEGIES` | `momentum,vwap,breakout,mean_reversion` | Active set |
| `WATCHLIST` | liquid US names + ETFs | Comma-separated |
| `MAX_DAILY_LOSS_PCT` | profile | Circuit breaker |
| `SURVIVAL_DRAWDOWN_PCT` | `2.0` | Enter survival on day drawdown |
| `SURVIVAL_GIVEBACK_PCT` | `0.5` | Enter survival on peak giveback |
| `SURVIVAL_POSITION_LOSS_PCT` | `1.5` | Enter survival if any position bleeds |
| `POSITION_CUT_PCT` | `2.0` | Cut losers in normal mode |
| `SURVIVAL_POSITION_CUT_PCT` | `1.0` | Cut losers faster in survival |
| `DRY_RUN` | `false` | Log decisions without ordering |
| `RECAP_EMAIL_TO` | — | Email address for daily close recap |
| `RESEND_API_KEY` | — | Send recap via [Resend](https://resend.com) |
| `SMTP_*` | — | Alternative: any SMTP provider |
| `RECAP_WEBHOOK_URL` | — | Optional Discord/Slack webhook |

Aggressive profile defaults: ~15% max position, 8 names, 1.5% risk/trade, 4% daily loss halt.

### Daily recap email

Every **weekday at ~4:05 PM ET** (after the US close), the bot emails a recap with day P/L, entries, exits, and open positions. Configure on Railway:

```
RECAP_EMAIL_TO=you@example.com
RESEND_API_KEY=re_xxxx   # free tier works; verify your domain or use Resend sandbox
SMTP_FROM=Alpaca Bot <onboarding@resend.dev>
```

Preview anytime: `python -m alpaca_bot recap` · Force send: `python -m alpaca_bot recap --send`

Recaps are also saved to `logs/recap-YYYY-MM-DD.txt`.

## Safety rails

- Paper trading by default  
- Mandatory bracket stop + take-profit on entries  
- No averaging down  
- PDT guard under $25k equity (blocks after 3 day trades / 5 days)  
- Flatten open risk `FLATTEN_MINUTES_BEFORE_CLOSE` before the session ends  
- Full audit trail in `data/bot.db` and `logs/bot.log`  

## Layout

```
alpaca-bot/
  src/alpaca_bot/
    cli.py           # status / once / run / backtest / flatten
    loop.py          # autonomous cycle
    risk.py          # sizing, PDT, survival, halt
    client.py        # Alpaca trading + bars
    indicators.py
    strategies/      # momentum, vwap, breakout, mean_reversion
    backtest.py
    state.py         # SQLite audit
  tests/
  .env.example
```

## Tests

```bash
cd alpaca-bot && pip install -e . && pytest -q
```

## Disclaimer

Trading stocks is risky and can lose money faster than you expect. This software is for education and paper trading first. You are solely responsible for API keys, live enablement, and regulatory constraints (including PDT). The viral “$75 → $6k overnight” stories are not a performance claim for this bot.
