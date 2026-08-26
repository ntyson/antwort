# Alpaca Day-Trading Bot

Autonomous stock day trader for [Alpaca](https://alpaca.markets/) paper (default) or live accounts.

Inspired by agent-style loops that scan on a timer, trade only when the edge is wide enough, size by conviction, and **change behavior under drawdown** (survival mode) instead of averaging down into a hole.

> No bot can guarantee the highest return. This one optimizes for high-conviction intraday momentum/VWAP/breakout edges with hard loss limits. Past or synthetic backtests are not predictive.

## What it does every cycle

1. Confirms the US equity session is open  
2. Syncs **normal / survival / halted** mode from day & week drawdown  
3. Manages exits (signal sells, survival cuts, EOD flatten)  
4. Pulls bars for the watchlist and runs four strategies  
5. Keeps only setups above the conviction threshold  
6. Sizes by risk × score (wider edge → larger size)  
7. Submits bracket orders (entry + stop + take-profit)  
8. Logs every risk decision and fill to SQLite  

### Survival mode (tweet-style adaptation)

When day drawdown hits `SURVIVAL_DRAWDOWN_PCT` (default 2%):

- Drops mean-reversion  
- Raises the minimum signal score  
- Halves position size and max concurrent names  
- Cuts open losers quickly  

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
| `SURVIVAL_DRAWDOWN_PCT` | `2.0` | Enter survival mode |
| `DRY_RUN` | `false` | Log decisions without ordering |

Aggressive profile defaults: ~15% max position, 8 names, 1.5% risk/trade, 4% daily loss halt.

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
