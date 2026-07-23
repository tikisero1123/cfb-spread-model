"""Shared helpers for the play-money pick'em. Used by pages/1_Pick_Em.py."""
import streamlit as st
from supabase import create_client

MIN_WEEKLY = 5     # picks needed to qualify for the week
MIN_STAKE = 10
MAX_STAKE = 20
MAX_WEEKLY = 20   # hard cap (also enforced by a DB trigger)
SPREAD_PRICE = -110
START_BALANCE = 1000  # per wallet


@st.cache_resource
def sb():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_ANON_KEY"])


# ---------- auth ----------
def current_user():
    return st.session_state.get("user")


def sign_up(email, password, display_name):
    res = sb().auth.sign_up({"email": email, "password": password})
    if res.user is None:
        raise RuntimeError("sign-up failed")
    sb().postgrest.auth(res.session.access_token)
    sb().table("profiles").insert(
        {"id": res.user.id, "display_name": display_name}
    ).execute()
    st.session_state["user"] = {"id": res.user.id, "email": email,
                                "token": res.session.access_token}


def sign_in(email, password):
    res = sb().auth.sign_in_with_password({"email": email, "password": password})
    sb().postgrest.auth(res.session.access_token)
    st.session_state["user"] = {"id": res.user.id, "email": email,
                                "token": res.session.access_token}


def sign_out():
    st.session_state.pop("user", None)


def _client():
    """Postgrest client authenticated as the signed-in user (RLS applies)."""
    u = current_user()
    sb().postgrest.auth(u["token"])
    return sb()


# ---------- data ----------
def profile():
    u = current_user()
    r = _client().table("profiles").select("*").eq("id", u["id"]).execute()
    return r.data[0] if r.data else None


def week_picks(season, week):
    u = current_user()
    r = (_client().table("picks").select("*")
         .eq("user_id", u["id"]).eq("season", season).eq("week", week)
         .order("placed_at").execute())
    return r.data


def american_payout(stake, odds):
    """Total returned to balance on a win (stake + profit)."""
    if odds < 0:
        return stake + stake * 100.0 / abs(odds)
    return stake + stake * odds / 100.0


def wallet_col(book):
    return "balance_tiki" if book == "tiki" else "balance_bov"


def place_pick(row, season, week, market, side, stake, book="bovada"):
    """row: schedule row. book: 'bovada' or 'tiki' (which line + which wallet)."""
    u = current_user()
    prof = profile()
    if not (MIN_STAKE <= stake <= MAX_STAKE):
        raise ValueError(f"stake must be between ${MIN_STAKE}$ and ${MAX_STAKE}$")
    wcol = wallet_col(book)
    if stake > prof[wcol]:
        raise ValueError("stake exceeds that wallet's balance")
    existing = week_picks(season, week)
    if len(existing) >= MAX_WEEKLY:
        raise ValueError(f"weekly limit of {MAX_WEEKLY} picks reached")

    pick = {
        "user_id": u["id"], "season": int(season), "week": int(week),
        "game_id": str(row["game_id"]),
        "home_team": row["home_team"], "away_team": row["away_team"],
        "market": market, "side": side, "stake": float(stake), "book": book,
    }
    if market == "spread":
        line = row["my_spread"] if book == "tiki" else row["spread"]
        pick["line"] = float(line)
        pick["odds"] = SPREAD_PRICE
    else:  # moneyline is bovada-only
        pick["book"] = "bovada"
        pick["odds"] = int(row["ml_home"] if side == "home" else row["ml_away"])

    c = _client()
    c.table("picks").insert(pick).execute()
    c.table("profiles").update(
        {wcol: float(prof[wcol]) - float(stake)}
    ).eq("id", u["id"]).execute()
