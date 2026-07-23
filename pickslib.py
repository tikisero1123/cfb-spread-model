"""Shared helpers for the play-money pick'em. Used by pages/1_Pick_Em.py."""
import streamlit as st
from supabase import create_client
from streamlit_cookies_controller import CookieController

_COOKIE = "pickem_session"


@st.cache_resource
def _cookies():
    return CookieController()

MIN_WEEKLY = 5     # picks needed to qualify for the week
MIN_STAKE = 5
MAX_STAKE = 20
MAX_WEEKLY = 10   # hard cap (also enforced by a DB trigger)
SPREAD_PRICE = -110
SIGMA = 16.2  # SD of margins around a line; same value the main app uses


def _phi(x):
    from math import erf, sqrt
    return 0.5 * (1 + erf(x / sqrt(2)))


def prob_to_american(p):
    p = min(max(p, 0.02), 0.98)  # clamp so odds stay sane on huge spreads
    if p >= 0.5:
        return -int(round(100 * p / (1 - p)))
    return int(round(100 * (1 - p) / p))


def tiki_ml_odds(my_spread, side):
    """Fair-value (no-vig) moneyline implied by Tiki's home-perspective spread."""
    p_home = _phi(-float(my_spread) / SIGMA)
    p = p_home if side == "home" else 1 - p_home
    return prob_to_american(p)
START_BALANCE = 1000  # per wallet


@st.cache_resource
def sb():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_ANON_KEY"])


# ---------- auth ----------
def current_user():
    u = st.session_state.get("user")
    if u:
        return u
    # try to restore a login from the browser cookie
    try:
        raw = _cookies().get(_COOKIE)
        if raw and isinstance(raw, dict) and raw.get("rt"):
            res = sb().auth.set_session(raw["at"], raw["rt"])
            if res and res.user:
                sb().postgrest.auth(res.session.access_token)
                st.session_state["user"] = {"id": res.user.id,
                                            "email": res.user.email,
                                            "token": res.session.access_token}
                _remember(res.session)
                _ensure_profile(res.user.id)
                return st.session_state["user"]
    except Exception:
        pass  # stale/invalid cookie -> just show the sign-in form
    return None


def _remember(session):
    try:
        _cookies().set(_COOKIE, {"at": session.access_token,
                                 "rt": session.refresh_token},
                       max_age=60 * 60 * 24 * 30)
    except Exception:
        pass


def _ensure_profile(uid):
    c = sb()
    have = c.table("profiles").select("id").eq("id", uid).execute()
    if not have.data:
        name = st.session_state.pop("pending_display_name", None) or "player"
        c.table("profiles").insert({"id": uid, "display_name": name}).execute()


def sign_up(email, password, display_name):
    res = sb().auth.sign_up({"email": email, "password": password})
    if res.user is None:
        raise RuntimeError("sign-up failed")
    if res.session is None:
        # email confirmation is on: no session yet -- finish on first sign-in
        st.session_state["pending_display_name"] = display_name
        raise RuntimeError("Account created! Check your email for a confirmation "
                           "link, then use the Sign in tab.")
    sb().postgrest.auth(res.session.access_token)
    sb().table("profiles").insert(
        {"id": res.user.id, "display_name": display_name}
    ).execute()
    st.session_state["user"] = {"id": res.user.id, "email": email,
                                "token": res.session.access_token}
    _remember(res.session)


def sign_in(email, password):
    res = sb().auth.sign_in_with_password({"email": email, "password": password})
    sb().postgrest.auth(res.session.access_token)
    st.session_state["user"] = {"id": res.user.id, "email": email,
                                "token": res.session.access_token}
    _remember(res.session)
    _ensure_profile(res.user.id)


def sign_out():
    st.session_state.pop("user", None)
    try:
        _cookies().remove(_COOKIE)
    except Exception:
        pass


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
    else:  # moneyline: bovada uses market odds, tiki uses fair odds from Tiki's spread
        if book == "tiki":
            pick["odds"] = tiki_ml_odds(row["my_spread"], side)
        else:
            pick["odds"] = int(row["ml_home"] if side == "home" else row["ml_away"])

    c = _client()
    c.table("picks").insert(pick).execute()
    c.table("profiles").update(
        {wcol: float(prof[wcol]) - float(stake)}
    ).eq("id", u["id"]).execute()
