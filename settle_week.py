"""Grade a finished week and pay out play-money balances.

Run locally after the week's games finish:
    python3 settle_week.py 2026 1

Needs env vars (or .env): CFBD_API_KEY, SUPABASE_URL, SUPABASE_SERVICE_KEY
(The SERVICE key, not the anon key -- settlement bypasses RLS on purpose.)
"""
import os, sys, requests
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()
SEASON, WEEK = int(sys.argv[1]), int(sys.argv[2])

# ---- final scores from CFBD ----
r = requests.get("https://apinext.collegefootballdata.com/games",
                 params={"year": SEASON, "week": WEEK, "seasonType": "regular"},
                 headers={"Authorization": f"Bearer {os.environ['CFBD_API_KEY']}"},
                 timeout=30)
r.raise_for_status()
finals = {str(g["id"]): (g["homePoints"], g["awayPoints"])
          for g in r.json()
          if g.get("completed") and g.get("homePoints") is not None}
print(f"{len(finals)} completed games for {SEASON} week {WEEK}")

sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
open_picks = (sb.table("picks").select("*").eq("season", SEASON)
              .eq("week", WEEK).eq("status", "open").execute().data)
print(f"{len(open_picks)} open picks to grade")


def payout(stake, odds):
    if odds < 0:
        return stake + stake * 100.0 / abs(odds)
    return stake + stake * odds / 100.0


credit, graded = {}, 0   # credit keyed by (user_id, wallet_column)
for p in open_picks:
    if p["game_id"] not in finals:
        continue  # game not final yet; grade on a later run
    hp, ap = finals[p["game_id"]]
    margin = hp - ap  # home perspective

    if p["market"] == "spread":
        edge = margin + float(p["line"])       # >0 home covers, <0 away covers
        if edge == 0:
            status, pay = "push", float(p["stake"])
        elif (edge > 0) == (p["side"] == "home"):
            status, pay = "won", payout(float(p["stake"]), int(p["odds"]))
        else:
            status, pay = "lost", 0.0
    else:  # moneyline
        if margin == 0:
            status, pay = "push", float(p["stake"])
        elif (margin > 0) == (p["side"] == "home"):
            status, pay = "won", payout(float(p["stake"]), int(p["odds"]))
        else:
            status, pay = "lost", 0.0

    sb.table("picks").update({"status": status, "payout": pay}).eq("id", p["id"]).execute()
    if pay > 0:
        wcol = "balance_tiki" if p.get("book") == "tiki" else "balance_bov"
        credit[(p["user_id"], wcol)] = credit.get((p["user_id"], wcol), 0.0) + pay
    graded += 1

for (uid, wcol), amt in credit.items():
    bal = sb.table("profiles").select(wcol).eq("id", uid).execute().data[0][wcol]
    sb.table("profiles").update({wcol: float(bal) + amt}).eq("id", uid).execute()

print(f"graded {graded} picks, credited {len(credit)} users")
