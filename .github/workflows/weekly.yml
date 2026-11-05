#!/usr/bin/env python3
"""Weekly stock-scoring agent. Paper mode by default.

  python weekly_investor.py            # score watchlist, "buy" in paper mode
  python weekly_investor.py --report   # paper portfolio performance
  python weekly_investor.py --force    # run again even if this week already ran
  python weekly_investor.py --live     # real orders (not wired yet, see PublicBroker)
Create a file named STOP in this folder to halt all buying.
"""
import argparse, csv, datetime as dt, json, math, os, sys

LEDGER = "ledger.csv"
FIELDS = ["week", "date", "mode", "ticker", "usd", "price", "shares"]

# metric: (bad value -> 0 pts, good value -> 1 pt, weight)
RULES = {
    "pe":            (45, 15, 2.0),     # lower is better
    "peg":           (3, 1, 1.5),
    "rev_growth":    (0, 0.15, 2.0),
    "profit_margin": (0, 0.20, 2.0),
    "debt_equity":   (200, 50, 1.0),
    "trend200":      (-0.15, 0.10, 1.5),  # price vs 200-day average
    "rsi":           (75, 40, 1.0),       # overbought = bad
}


def lerp(x, bad, good):
    if x is None:
        return None
    return max(0.0, min(1.0, (x - bad) / (good - bad)))


def num(x):
    try:
        x = float(x)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def rsi(prices, n=14):
    d = prices.diff().dropna().tail(n)
    up, dn = d.clip(lower=0).mean(), (-d.clip(upper=0)).mean()
    return 100.0 if dn == 0 else 100 - 100 / (1 + up / dn)


# ---------- data ----------
def fetch_stock(ticker):
    import yfinance as yf
    t = yf.Ticker(ticker)
    info = t.info or {}
    _INFO[ticker] = info
    px = t.history(period="1y")["Close"].dropna()
    m = {"pe": num(info.get("trailingPE")),
         "peg": num(info.get("pegRatio") or info.get("trailingPegRatio")),
         "rev_growth": num(info.get("revenueGrowth")),
         "profit_margin": num(info.get("profitMargins")),
         "debt_equity": num(info.get("debtToEquity"))}
    if len(px) >= 200:
        m["trend200"] = float(px.iloc[-1] / px.tail(200).mean() - 1)
        m["rsi"] = float(rsi(px))
    return float(px.iloc[-1]), m


def market_score():
    import yfinance as yf
    spx = yf.Ticker("^GSPC").history(period="1y")["Close"].dropna()
    vix = float(yf.Ticker("^VIX").history(period="5d")["Close"].dropna().iloc[-1])
    trend = float(spx.iloc[-1] / spx.tail(200).mean() - 1)
    score = 100 * (0.6 * lerp(trend, -0.10, 0.08) + 0.4 * lerp(vix, 35, 14))
    return score, {"sp500_vs_200d": round(trend, 3), "vix": round(vix, 1)}


_INFO, _DETAIL = {}, {}
INDICES = {"^GSPC": "S&P 500", "^IXIC": "Nasdaq", "^DJI": "Dow", "^RUT": "Russell 2000",
           "^VIX": "VIX", "^TNX": "10Y yield"}
SECTORS = {"XLK": "Technology", "XLF": "Financials", "XLV": "Health Care", "XLE": "Energy",
           "XLY": "Consumer Discretionary", "XLP": "Consumer Staples", "XLI": "Industrials",
           "XLU": "Utilities", "XLB": "Materials", "XLRE": "Real Estate", "XLC": "Communication"}
INFO_KEYS = ["longName", "sector", "industry", "marketCap", "trailingPE", "forwardPE", "priceToBook",
             "beta", "fiftyTwoWeekHigh", "fiftyTwoWeekLow", "totalRevenue", "revenueGrowth",
             "grossMargins", "operatingMargins", "profitMargins", "ebitda", "freeCashflow",
             "operatingCashflow", "totalCash", "totalDebt", "debtToEquity", "returnOnEquity"]


def perf(sym):
    import yfinance as yf
    px = yf.Ticker(sym).history(period="3mo")["Close"].dropna()
    last, prev, mo = float(px.iloc[-1]), float(px.iloc[-2]), float(px.iloc[-22])
    return {"price": round(last, 2), "d1": round(100 * (last / prev - 1), 2),
            "d1a": round(last - prev, 2), "m1": round(100 * (last / mo - 1), 2)}


def overview():
    out = {"indices": {}, "sectors": {}}
    for group, syms in (("indices", INDICES), ("sectors", SECTORS)):
        for sym, name in syms.items():
            try:
                out[group][name] = perf(sym)
            except Exception:
                pass
    return out


def fetch_details(t):
    """Key stats from the info cached by fetch_stock, plus 4 years of annual results."""
    i = _INFO.get(t, {})
    d = {k: (i.get(k) if isinstance(i.get(k), str) else num(i.get(k))) for k in INFO_KEYS}
    hist = {}
    try:
        import yfinance as yf
        tk = yf.Ticker(t)
        for label, df, row in (("revenue", tk.income_stmt, "Total Revenue"),
                               ("net_income", tk.income_stmt, "Net Income"),
                               ("fcf", tk.cashflow, "Free Cash Flow")):
            if row in df.index:
                ser = df.loc[row].dropna().sort_index().tail(4)
                hist[label] = [[str(k.year), float(v)] for k, v in ser.items()]
    except Exception:
        pass
    d["history"] = hist
    return d


def breakdown(m):
    return [{"k": k, "v": round(m[k], 4), "pts": round(100 * lerp(m[k], b, g)), "w": w}
            for k, (b, g, w) in RULES.items() if m.get(k) is not None]


# ---------- scoring + planning ----------
def score_stock(m):
    """0-100 score; metrics that are missing are dropped and weights re-normalised."""
    pts = wsum = used = 0
    for k, (bad, good, w) in RULES.items():
        s = lerp(m.get(k), bad, good)
        if s is not None:
            pts += s * w
            wsum += w
            used += 1
    return (100 * pts / wsum if wsum else None), used


def make_plan(cfg, scores, mkt):
    """Return ({ticker: usd}, note). scores = {ticker: (score, n_metrics)}."""
    if mkt < cfg["market_floor"]:
        return {}, f"Market score {mkt:.0f} below floor {cfg['market_floor']}: buying paused."
    thr = cfg["buy_threshold"] + (cfg["weak_market_bump"] if mkt < 50 else 0)
    passers = [t for t, (s, n) in scores.items()
               if s is not None and n >= cfg["min_metrics"] and s >= thr]
    alloc = cfg["allocation"]
    weights = ({t: float(p) for t, p in alloc["percent"].items()}
               if alloc["mode"] == "percent" else {t: 1.0 for t in scores})
    pool = passers if cfg["if_stock_fails"] == "redistribute" else list(scores)
    denom = sum(weights.get(t, 0) for t in pool)
    if not passers or denom == 0:
        return {}, f"No stock cleared the threshold ({thr:.0f}). Nothing bought."
    orders = {t: round(min(cfg["weekly_budget_usd"] * weights.get(t, 0) / denom,
                           cfg["max_order_usd"]), 2) for t in passers}
    return {t: usd for t, usd in orders.items() if usd >= 1}, f"Threshold {thr:.0f}."


# ---------- brokers / ledger ----------
def ledger_rows():
    if not os.path.exists(LEDGER):
        return []
    with open(LEDGER, newline="") as f:
        return list(csv.DictReader(f))


def log_trade(week, mode, ticker, usd, price):
    new = not os.path.exists(LEDGER)
    with open(LEDGER, "a", newline="") as f:
        w = csv.DictWriter(f, FIELDS)
        if new:
            w.writeheader()
        w.writerow({"week": week, "date": dt.date.today().isoformat(), "mode": mode,
                    "ticker": ticker, "usd": usd, "price": round(price, 4),
                    "shares": round(usd / price, 6)})


class PaperBroker:
    mode = "paper"

    def buy(self, ticker, usd, price, week):
        log_trade(week, self.mode, ticker, usd, price)


class PublicBroker:
    """Placeholder. Wire this to Public.com's Trading API (or its CLI) only after
    checking the order payload in their docs, and test with a tiny amount."""
    mode = "live"

    def buy(self, ticker, usd, price, week):
        raise NotImplementedError("Live ordering is not wired up yet.")


def positions(prices):
    """Paper holdings valued at current prices. Fetches prices missing from `prices`."""
    rows = [r for r in ledger_rows() if r["mode"] == "paper"]
    out = []
    for t in sorted({r["ticker"] for r in rows}):
        rs = [r for r in rows if r["ticker"] == t]
        usd, sh = sum(float(r["usd"]) for r in rs), sum(float(r["shares"]) for r in rs)
        if t not in prices:
            try:
                prices[t] = fetch_stock(t)[0]
            except Exception:
                continue
        out.append({"ticker": t, "invested": round(usd, 2), "value": round(prices[t] * sh, 2)})
    return out


def report():
    pos = positions({})
    if not pos:
        return print("No paper trades yet.")
    for p in pos:
        print(f"{p['ticker']:6} invested ${p['invested']:8.2f}  now ${p['value']:8.2f}  "
              f"{100 * (p['value'] / p['invested'] - 1):+6.1f}%")
    inv, val = sum(p["invested"] for p in pos), sum(p["value"] for p in pos)
    print(f"TOTAL  invested ${inv:8.2f}  now ${val:8.2f}  {100 * (val / inv - 1):+6.1f}%")


def write_dashboard(cfg, mode, mkt, detail, scores, orders, prices, note):
    """Write docs/data.json, which docs/index.html (GitHub Pages) displays."""
    data = {
        "updated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "mode": mode, "note": note, "floor": cfg["market_floor"],
        "threshold": cfg["buy_threshold"] + (cfg["weak_market_bump"] if mkt < 50 else 0),
        "market": {"score": round(mkt), **detail},
        "budget": cfg["weekly_budget_usd"], "allocation": cfg["allocation"]["mode"],
        "if_stock_fails": cfg["if_stock_fails"],
        "stocks": [{"ticker": t, "score": None if s is None else round(s, 1), "metrics": n,
                    "order": orders.get(t, 0), **_DETAIL.get(t, {})} for t, (s, n) in scores.items()],
        "positions": positions(prices), "overview": overview(),
        "trades": ledger_rows()[-15:][::-1],
    }
    os.makedirs("docs", exist_ok=True)
    with open("docs/data.json", "w") as f:
        json.dump(data, f, indent=1)


# ---------- main ----------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    if a.report:
        return report()
    cfg = json.load(open(a.config))
    if os.path.exists("STOP"):
        sys.exit("STOP file found. Not trading.")
    broker = PublicBroker() if (a.live or cfg["mode"] == "live") else PaperBroker()
    week = dt.date.today().strftime("%G-W%V")
    if not a.force and any(r["week"] == week and r["mode"] == broker.mode for r in ledger_rows()):
        sys.exit(f"Already ran for {week} ({broker.mode}). Use --force to rerun.")

    alloc = cfg["allocation"]
    tickers = list(alloc["percent"]) if alloc["mode"] == "percent" else cfg["watchlist"]
    if alloc["mode"] == "percent" and abs(sum(alloc["percent"].values()) - 100) > 0.01:
        sys.exit("allocation.percent must add up to 100.")

    mkt, detail = market_score()
    print(f"Market score {mkt:.0f}/100  {detail}")
    scores, prices = {}, {}
    for t in tickers:
        try:
            prices[t], m = fetch_stock(t)
            scores[t] = score_stock(m)
            _DETAIL[t] = {"price": round(prices[t], 2), "breakdown": breakdown(m),
                          "info": fetch_details(t)}
        except Exception as e:
            print(f"  {t}: data error ({e}); skipped")
            continue
        s, n = scores[t]
        print(f"  {t:6} score {s:5.1f}  ({n} metrics)" if s is not None else f"  {t:6} no data")

    orders, note = make_plan(cfg, scores, mkt)
    print(note)
    for t, usd in orders.items():
        broker.buy(t, usd, prices[t], week)
        print(f"  [{broker.mode}] BUY ${usd:.2f} {t} @ {prices[t]:.2f}")
    print(f"Total: ${sum(orders.values()):.2f} of ${cfg['weekly_budget_usd']} budget.")
    write_dashboard(cfg, broker.mode, mkt, detail, scores, orders, prices, note)


if __name__ == "__main__":
    main()
