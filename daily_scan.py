#!/usr/bin/env python3
"""Daily market scan with $1,000/day paper trading. Shares its scoring with weekly_investor.py.

  python daily_scan.py          # scan, score, paper-buy
  python daily_scan.py --force  # run even if today already ran or the market was closed
Stage 1 ranks the whole universe by price trend (one bulk download). Stage 2 pulls full
fundamentals for the top candidates and scores them. Top scorers above the threshold get
an equal slot of the daily budget (budget / max_picks); unused slots stay in cash.
"""
import argparse, csv, datetime as dt, json, os, sys, time
import weekly_investor as w

LEDGER = "ledger_daily.csv"
FIELDS = ["date", "ticker", "usd", "price", "shares", "score"]


def rows():
    if not os.path.exists(LEDGER):
        return []
    with open(LEDGER, newline="") as f:
        return list(csv.DictReader(f))


def tech_rank(universe):
    import yfinance as yf
    px = yf.download(universe, period="1y", auto_adjust=True, progress=False)["Close"]
    px = px.dropna(axis=1, how="all")
    ranks = {}
    for t in px.columns:
        s = px[t].dropna()
        if len(s) >= 200:
            ranks[t] = w.score_stock({"trend200": float(s.iloc[-1] / s.tail(200).mean() - 1),
                                      "rsi": float(w.rsi(s))})[0]
    return px, ranks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    cfg = json.load(open(a.config))
    sc = cfg["scan"]
    if os.path.exists("STOP"):
        sys.exit("STOP file found. Not trading.")
    today = dt.date.today().isoformat()
    if not a.force and any(r["date"] == today for r in rows()):
        sys.exit("Already ran today. Use --force to rerun.")
    universe = [l.split("#")[0].strip().upper() for l in open(sc["universe_file"])]
    universe = [u for u in universe if u]

    px, ranks = tech_rank(universe)
    if not a.force and px.index[-1].date().isoformat() != today:
        sys.exit("No new prices today (market closed). Use --force to run anyway.")
    mkt, detail = w.market_score()
    print(f"Scanned {len(ranks)} stocks. Market score {mkt:.0f}/100 {detail}")

    scored, prices = {}, {}
    for t in sorted(ranks, key=ranks.get, reverse=True)[: sc["candidates"]]:
        try:
            prices[t], m = w.fetch_stock(t)
            scored[t] = w.score_stock(m)
        except Exception as e:
            print(f"  {t}: data error ({e}); skipped")
        time.sleep(0.2)

    held = {}
    for r in rows():
        held[r["ticker"]] = held.get(r["ticker"], 0) + float(r["usd"])
    thr = cfg["buy_threshold"] + (cfg["weak_market_bump"] if mkt < 50 else 0)
    order = sorted(scored, key=lambda t: -(scored[t][0] or 0))
    if mkt < cfg["market_floor"]:
        picks, note = [], f"Market score {mkt:.0f} below floor {cfg['market_floor']}: buying paused."
    else:
        ok = [t for t in order if scored[t][0] is not None and scored[t][1] >= cfg["min_metrics"]
              and scored[t][0] >= thr and held.get(t, 0) < sc["max_per_ticker_usd"]]
        picks = ok[: sc["max_picks"]]
        note = f"Threshold {thr:.0f}. {len(ok)} cleared it." if ok else f"No stock cleared {thr:.0f}."
    slot = round(sc["budget_usd"] / sc["max_picks"], 2)
    print(note)

    new = not os.path.exists(LEDGER)
    with open(LEDGER, "a", newline="") as f:
        wr = csv.DictWriter(f, FIELDS)
        if new:
            wr.writeheader()
        for t in picks:
            wr.writerow({"date": today, "ticker": t, "usd": slot, "price": round(prices[t], 4),
                         "shares": round(slot / prices[t], 6), "score": round(scored[t][0], 1)})
            print(f"  [paper] BUY ${slot:.2f} {t} @ {prices[t]:.2f} (score {scored[t][0]:.0f})")
    print(f"Spent ${slot * len(picks):.2f} of ${sc['budget_usd']} today.")

    last = {t: float(px[t].dropna().iloc[-1]) for t in px.columns}
    pos = {}
    for r in rows():
        p = pos.setdefault(r["ticker"], [0.0, 0.0])
        p[0] += float(r["usd"]); p[1] += float(r["shares"])
    positions = [{"ticker": t, "invested": round(u, 2), "value": round(sh * last.get(t, 0), 2)}
                 for t, (u, sh) in sorted(pos.items())]
    hist = []
    if os.path.exists("docs/daily.json"):
        try:
            hist = [h for h in json.load(open("docs/daily.json")).get("history", []) if h["date"] != today]
        except Exception:
            pass
    hist.append({"date": today, "invested": round(sum(p["invested"] for p in positions), 2),
                 "value": round(sum(p["value"] for p in positions), 2)})
    data = {"updated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "market": {"score": round(mkt), **detail}, "threshold": thr, "note": note,
            "budget": sc["budget_usd"], "slot": slot, "scanned": len(ranks),
            "candidates": [{"ticker": t, "tech": round(ranks[t], 1),
                            "score": None if scored[t][0] is None else round(scored[t][0], 1),
                            "n": scored[t][1], "order": slot if t in picks else 0} for t in order[:20]],
            "positions": positions, "history": hist[-90:], "trades": rows()[-30:][::-1]}
    os.makedirs("docs", exist_ok=True)
    with open("docs/daily.json", "w") as f:
        json.dump(data, f, indent=1)


if __name__ == "__main__":
    main()
