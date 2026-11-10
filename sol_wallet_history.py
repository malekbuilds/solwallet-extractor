"""
solana wallet history extractor

what it does:
  1. gets every transaction signature of the wallet (all pages)
  2. downloads each transaction
  3. works out sol change and token change for that wallet
  4. saves a csv (one row per token move) and a raw jsonl backup

usage:
  pip install requests
  python sol_wallet_history.py
  python sol_wallet_history.py --wallet <address> --workers 4

tip: the free public rpc is slow and blocks you fast.
get a free key at helius.dev or quicknode and set it like this:
  export SOLANA_RPC_URL="https://mainnet.helius-rpc.com/?api-key=YOUR_KEY"
"""

import os
import sys
import csv
import json
import time
import argparse
import threading
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

DEFAULT_WALLET = "5aLY85pyxiuX3fd4RgM3Yc1e3MAL6b7UgaZz6MS3JUfG"
RPC_URL = os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
WSOL_MINT = "So11111111111111111111111111111111111111112"
LAMPORTS = 1_000_000_000

session = requests.Session()
lock = threading.Lock()


def rpc(method, params, retries=8):
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    wait = 1.0
    for _ in range(retries):
        try:
            r = session.post(RPC_URL, json=payload, timeout=40)
            if r.status_code == 429:
                time.sleep(wait)
                wait = min(wait * 2, 30)
                continue
            r.raise_for_status()
            data = r.json()
            if "error" in data:
                err = data["error"]
                msg = str(err.get("message", "")).lower()
                if err.get("code") == 429 or "rate" in msg or "too many" in msg:
                    time.sleep(wait)
                    wait = min(wait * 2, 30)
                    continue
                raise RuntimeError(f"rpc error: {err}")
            return data["result"]
        except requests.RequestException:
            time.sleep(wait)
            wait = min(wait * 2, 30)
    raise RuntimeError(f"rpc failed after retries: {method}")


def get_all_signatures(wallet):
    sigs = []
    before = None
    while True:
        opts = {"limit": 1000, "commitment": "confirmed"}
        if before:
            opts["before"] = before
        batch = rpc("getSignaturesForAddress", [wallet, opts])
        if not batch:
            break
        sigs.extend(batch)
        before = batch[-1]["signature"]
        print(f"signatures found: {len(sigs)}", flush=True)
        if len(batch) < 1000:
            break
    return sigs


def get_tx(signature):
    return rpc(
        "getTransaction",
        [
            signature,
            {
                "encoding": "jsonParsed",
                "maxSupportedTransactionVersion": 0,
                "commitment": "confirmed",
            },
        ],
    )


def load_cache(path):
    cache = {}
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    cache[obj["signature"]] = obj["tx"]
                except Exception:
                    continue
    return cache


def parse_tx(wallet, signature, tx):
    """returns a list of rows (one per token that moved in the wallet)"""
    if not tx:
        return []

    meta = tx.get("meta") or {}
    block_time = tx.get("blockTime")
    when = (
        datetime.fromtimestamp(block_time, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        if block_time
        else ""
    )
    failed = meta.get("err") is not None

    keys = tx["transaction"]["message"]["accountKeys"]
    pubkeys = [k["pubkey"] if isinstance(k, dict) else k for k in keys]

    sol_change = 0.0
    fee_sol = (meta.get("fee") or 0) / LAMPORTS
    if wallet in pubkeys:
        idx = pubkeys.index(wallet)
        pre = meta.get("preBalances", [])
        post = meta.get("postBalances", [])
        if idx < len(pre) and idx < len(post):
            sol_change = (post[idx] - pre[idx]) / LAMPORTS
    fee_paid = fee_sol if pubkeys and pubkeys[0] == wallet else 0.0

    # token changes for this wallet (grouped by mint)
    deltas = {}

    def add(balances, sign):
        for b in balances or []:
            if b.get("owner") != wallet:
                continue
            mint = b.get("mint")
            amt = b.get("uiTokenAmount", {})
            raw = int(amt.get("amount", "0"))
            dec = int(amt.get("decimals", 0))
            d = deltas.setdefault(mint, {"raw": 0, "dec": dec})
            d["raw"] += sign * raw
            d["dec"] = dec

    add(meta.get("preTokenBalances"), -1)
    add(meta.get("postTokenBalances"), +1)

    rows = []
    for mint, d in deltas.items():
        if mint == WSOL_MINT:
            continue  # wrapped sol is counted in the sol change
        amount = d["raw"] / (10 ** d["dec"])
        if amount == 0:
            continue
        if amount > 0 and sol_change < 0:
            side = "buy"
        elif amount < 0 and sol_change > 0:
            side = "sell"
        elif amount > 0:
            side = "receive"
        else:
            side = "send"

        # sol change without the fee, so you see the real trade size
        sol_trade = sol_change + fee_paid
        price = abs(sol_trade / amount) if amount else 0

        rows.append(
            {
                "time_utc": when,
                "block_time": block_time,
                "slot": tx.get("slot"),
                "signature": signature,
                "status": "failed" if failed else "ok",
                "side": side,
                "mint": mint,
                "token_amount": amount,
                "sol_change_total": round(sol_change, 9),
                "fee_sol": round(fee_paid, 9),
                "approx_price_sol_per_token": price,
            }
        )

    # if no token moved, still record sol-only tx (transfers, failed tx, etc.)
    if not rows:
        rows.append(
            {
                "time_utc": when,
                "block_time": block_time,
                "slot": tx.get("slot"),
                "signature": signature,
                "status": "failed" if failed else "ok",
                "side": "sol_only",
                "mint": "",
                "token_amount": 0,
                "sol_change_total": round(sol_change, 9),
                "fee_sol": round(fee_paid, 9),
                "approx_price_sol_per_token": 0,
            }
        )
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wallet", default=DEFAULT_WALLET)
    ap.add_argument("--workers", type=int, default=4, help="parallel downloads")
    ap.add_argument("--out", default=None, help="csv file name")
    args = ap.parse_args()

    wallet = args.wallet
    csv_path = args.out or f"history_{wallet[:6]}.csv"
    raw_path = f"raw_{wallet[:6]}.jsonl"

    print(f"wallet: {wallet}")
    print(f"rpc: {RPC_URL.split('?')[0]}")

    sigs = get_all_signatures(wallet)
    print(f"total transactions: {len(sigs)}")

    cache = load_cache(raw_path)
    todo = [s["signature"] for s in sigs if s["signature"] not in cache]
    print(f"already saved: {len(cache)} | to download: {len(todo)}")

    if todo:
        done = 0
        with open(raw_path, "a", encoding="utf-8") as raw_file:
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                futures = {pool.submit(get_tx, sig): sig for sig in todo}
                for fut in as_completed(futures):
                    sig = futures[fut]
                    try:
                        tx = fut.result()
                    except Exception as e:
                        print(f"skip {sig[:10]}...: {e}", file=sys.stderr)
                        continue
                    with lock:
                        cache[sig] = tx
                        raw_file.write(json.dumps({"signature": sig, "tx": tx}) + "\n")
                        raw_file.flush()
                        done += 1
                        if done % 25 == 0 or done == len(todo):
                            print(f"downloaded {done}/{len(todo)}", flush=True)

    all_rows = []
    for s in sigs:
        sig = s["signature"]
        if sig in cache:
            all_rows.extend(parse_tx(wallet, sig, cache[sig]))

    all_rows.sort(key=lambda r: r["block_time"] or 0)

    fields = [
        "time_utc", "block_time", "slot", "signature", "status", "side", "mint",
        "token_amount", "sol_change_total", "fee_sol", "approx_price_sol_per_token",
    ]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(all_rows)

    buys = sum(1 for r in all_rows if r["side"] == "buy")
    sells = sum(1 for r in all_rows if r["side"] == "sell")
    print(f"done. rows: {len(all_rows)} | buys: {buys} | sells: {sells}")
    print(f"saved: {csv_path} and {raw_path}")


if __name__ == "__main__":
    main()
