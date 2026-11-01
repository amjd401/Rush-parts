#!/usr/bin/env python3
"""Refresh prices, discounts and stock for every part in catalog.json from parts.toyota.com.sa.
Usage: python3 refresh.py [catalog.json] [data.json]
Keeps the previous value for any part that fails to load, so a bad run never blanks the page."""
import json, re, subprocess, sys, time, datetime, os
from concurrent.futures import ThreadPoolExecutor

cat_path = sys.argv[1] if len(sys.argv) > 1 else 'catalog.json'
out_path = sys.argv[2] if len(sys.argv) > 2 else 'data.json'
cat = json.load(open(cat_path, encoding='utf-8'))
codes = []
for it in cat:
    codes.append(it['pn'])
    codes += [a[0] for a in it.get('alt', [])]
codes = list(dict.fromkeys(codes))

old, history = {}, []
if os.path.exists(out_path):
    try:
        prev = json.load(open(out_path, encoding='utf-8'))
        old, history = prev.get('parts', {}), prev.get('history', [])
    except Exception: old, history = {}, []

def fetch(pn):
    for attempt in range(4):
        try:
            t = subprocess.run(['curl', '-s', '-m', '60', f'https://parts.toyota.com.sa/en/search/{pn}?pageSize=4'],
                               capture_output=True, text=True).stdout
            m = re.search(r'<script id="serverApp-state" type="application/json">(.*?)</script>', t, re.S)
            if not m: raise ValueError('no state')
            s = m.group(1).replace('&q;', '"').replace('&a;', '&').replace('&s;', "'").replace('&l;', '<').replace('&g;', '>')
            prods = json.loads(s)['cx-state']['product']['search']['results'].get('products', [])
            p = next((x for x in prods if x['code'].upper() == pn.upper()), None)
            if not p: return pn, {'missing': True}
            price = p.get('price', {}).get('value')
            dp = p.get('discountedPrice') or {}
            pct = dp.get('percentageDiscount') or p.get('price', {}).get('percentageDiscount') or 0
            now = dp.get('valueWithDiscount') if pct else price
            st = (p.get('stock') or {}).get('stockLevelStatus', 'unknown')
            return pn, {'name': p.get('name'), 'price': price, 'now': now, 'pct': pct, 'stock': st}
        except Exception:
            time.sleep(3 + attempt * 4)
    return pn, None

with ThreadPoolExecutor(3) as ex:
    res = dict(ex.map(fetch, codes))

parts, failed = {}, []
for pn in codes:
    if res.get(pn) is None:
        failed.append(pn)
        if pn in old: parts[pn] = old[pn]
    else:
        parts[pn] = res[pn]

riyadh = datetime.timezone(datetime.timedelta(hours=3))
stamp = datetime.datetime.now(riyadh).isoformat(timespec='minutes')
changes = sum(1 for k, v in parts.items() if k in old and any(old[k].get(f) != v.get(f) for f in ('price', 'now', 'stock')))
history = ([{'at': stamp, 'ok': len(codes) - len(failed), 'total': len(codes), 'changes': changes}] + history)[:12]
data = {'checked_at': stamp, 'parts': parts, 'failed': failed, 'history': history}
json.dump(data, open(out_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
ok = len(codes) - len(failed)
print(f'checked {ok}/{len(codes)} parts; failed: {failed}')
print('25%+ discounts:', [k for k, v in parts.items() if (v.get('pct') or 0) >= 25])
