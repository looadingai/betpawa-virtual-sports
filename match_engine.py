"""
Match Engine — Real 90-minute matches, admin-controlled final scores,
staggered individual kickoff times. Finished matches auto-deleted after 10 mins.
SQLite version for Render with match history.
"""
import random
import threading
import time
from zoneinfo import ZoneInfo
import os
import json
import sqlite3
from datetime import datetime, timedelta, timezone

# Use the same data directory as db.py
if 'RENDER' in os.environ:
    DATA_DIR = '/opt/render/project/src/data'
else:
    DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')

os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, 'betpawa.db')

# Cleanup delay for finished matches (10 minutes = 600 seconds)
CLEANUP_DELAY = 600  # Changed from 300 to 600 seconds (10 minutes)

# Match history retention (6 hours = 21600 seconds)
HISTORY_RETENTION = 21600  # 6 hours

# ── Leagues ────────────────────────────────────────────────────────────────
LEAGUES = {
    'english': {
        'name': 'English League', 'flag': '🏴󠁧󠁢󠁥󠁮󠁧󠁿',
        'teams': [
            ('ARS','Arsenal'),('AVL','Aston Villa'),('BHA','Brighton'),
            ('BOU','Bournemouth'),('BRE','Brentford'),('BUR','Burnley'),
            ('CHE','Chelsea'),('CRY','Crystal Palace'),('EVE','Everton'),
            ('FUL','Fulham'),('LEE','Leeds Utd'),('LEI','Leicester'),
            ('LIV','Liverpool'),('MCI','Man City'),('MUN','Man United'),
            ('NEW','Newcastle'),('NOT','Nott\'m Forest'),('SHU','Sheffield Utd'),
            ('SUN','Sunderland'),('TOT','Tottenham'),('WHU','West Ham'),
            ('WOL','Wolves'),('SOT','Southampton'),('LUT','Luton'),
        ]
    },
    'spanish': {
        'name': 'Spanish League', 'flag': '🇪🇸',
        'teams': [
            ('ALM','Almeria'),('ATH','Athletic Bilbao'),('ATM','Atletico Madrid'),
            ('BAR','Barcelona'),('BET','Real Betis'),('CAD','Cadiz'),
            ('CEL','Celta Vigo'),('GET','Getafe'),('GIR','Girona'),
            ('GRA','Granada'),('LAS','Las Palmas'),('MAL','Mallorca'),
            ('OSA','Osasuna'),('RAY','Rayo Vallecano'),('RMA','Real Madrid'),
            ('RSO','Real Sociedad'),('SEV','Sevilla'),('VAL','Valencia'),
            ('VIL','Villarreal'),('ALV','Alaves'),
        ]
    },
    'italian': {
        'name': 'Italian League', 'flag': '🇮🇹',
        'teams': [
            ('ATA','Atalanta'),('BOL','Bologna'),('CAG','Cagliari'),
            ('EMP','Empoli'),('FIO','Fiorentina'),('FRO','Frosinone'),
            ('GEN','Genoa'),('HEL','Hellas Verona'),('INT','Inter Milan'),
            ('JUV','Juventus'),('LAZ','Lazio'),('LEC','Lecce'),
            ('MIL','AC Milan'),('MON','Monza'),('NAP','Napoli'),
            ('ROM','Roma'),('SAL','Salernitana'),('SAS','Sassuolo'),
            ('TOR','Torino'),('UDI','Udinese'),
        ]
    }
}

PLAYERS = {
    'ARS':['Saka','Martinelli','Odegaard','Havertz','Trossard'],
    'LIV':['Salah','Nunez','Diaz','Szoboszlai','Mac Allister'],
    'MCI':['Haaland','De Bruyne','Foden','Doku','Bernardo'],
    'MUN':['Rashford','Fernandes','Hojlund','Antony','Mainoo'],
    'CHE':['Palmer','Jackson','Sterling','Mudryk','Gallagher'],
    'TOT':['Son','Richarlison','Maddison','Kulusevski','Bissouma'],
    'NEW':['Isak','Wilson','Almiron','Trippier','Joelinton'],
    'BHA':['Mitoma','Welbeck','Gross','March','Baleba'],
    'RMA':['Vinicius','Bellingham','Rodrygo','Valverde','Kroos'],
    'BAR':['Yamal','Lewandowski','Pedri','Gavi','Raphinha'],
    'ATM':['Griezmann','Morata','Correa','Felix','Llorente'],
    'JUV':['Vlahovic','Chiesa','Kean','Yildiz','Kostic'],
    'INT':['Lautaro','Thuram','Calhanoglu','Barella','Dimarco'],
    'MIL':['Giroud','Leao','Pulisic','Theo','Reijnders'],
    'NAP':['Osimhen','Kvaratskhelia','Politano','Zielinski','Di Lorenzo'],
}

active_simulations = {}

# ── Raw DB connection (used inside threads, no Flask context) ──────────────
def _db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def _q(conn, sql, params=()):
    """Thread-safe query helper."""
    return conn.execute(sql, params).fetchall()

def _ex(conn, sql, params=()):
    """Thread-safe execute helper, returns last inserted id."""
    cur = conn.execute(sql, params)
    conn.commit()
    return cur.lastrowid

# ── Helpers ────────────────────────────────────────────────────────────────
def get_player(code):
    return random.choice(PLAYERS.get(code, ['Player A', 'Player B', 'Player C']))

def _now_str():
    """Return current EAT time as string"""
    eat_tz = ZoneInfo('Africa/Nairobi')
    return datetime.now(eat_tz).strftime('%Y-%m-%d %H:%M:%S')

def _get_eat_time():
    """Return current East Africa Time (UTC+3) as datetime object"""
    eat_tz = ZoneInfo('Africa/Nairobi')
    return datetime.now(eat_tz)

# ── Odds generation ────────────────────────────────────────────────────────
def generate_odds(home_code, away_code):
    home_bias = random.uniform(0.35, 0.55)
    draw_prob = random.uniform(0.22, 0.30)
    away_prob = max(0.10, 1 - home_bias - draw_prob)
    mg = 1.08
    def o(p): return round(max(1.10, (1/p)/mg*mg), 2)
    h, d, a = o(home_bias), o(draw_prob), o(away_prob)
    ou = {
        'over_1.5':  round(random.uniform(1.08, 1.25), 2),
        'under_1.5': round(random.uniform(4.00, 7.00), 2),
        'over_2.5':  round(random.uniform(1.35, 1.70), 2),
        'under_2.5': round(random.uniform(2.20, 2.90), 2),
        'over_3.5':  round(random.uniform(2.00, 2.60), 2),
        'under_3.5': round(random.uniform(1.50, 1.75), 2),
    }
    btts = {'yes': round(random.uniform(1.45,1.75),2), 'no': round(random.uniform(1.90,2.50),2)}
    dc   = {
        '1X': round(max(1.05, 1/(home_bias+draw_prob)*0.93), 2),
        'X2': round(max(1.05, 1/(draw_prob+away_prob)*0.93), 2),
        '12': round(max(1.05, 1/(home_bias+away_prob)*0.93), 2),
    }
    htft = {
        '1/1': round(random.uniform(1.90,3.20),2), '1/X': round(random.uniform(14,22),2),
        '1/2': round(random.uniform(40,65),2),      'X/1': round(random.uniform(4,6),2),
        'X/X': round(random.uniform(6.5,9),2),      'X/2': round(random.uniform(11,16),2),
        '2/1': round(random.uniform(22,35),2),      '2/X': round(random.uniform(18,26),2),
        '2/2': round(random.uniform(8,12),2),
    }
    cs = {}
    for hg in range(6):
        for ag in range(6):
            base = 6 + (hg+ag)*4 + abs(hg-ag)*2
            cs[f'{hg}-{ag}'] = round(random.uniform(base*0.8, base*1.3), 2)
    cs['other'] = round(random.uniform(55, 80), 2)
    return {'1x2':{'1':h,'X':d,'2':a}, 'ou':ou, 'btts':btts, 'dc':dc, 'htft':htft, 'cs':cs}

# ── Fixture creation ───────────────────────────────────────────────────────
def make_pairs(league_key):
    teams = LEAGUES[league_key]['teams'].copy()
    random.shuffle(teams)
    pairs, used = [], set()
    for t in teams:
        if t[0] in used: continue
        for t2 in teams:
            if t2[0] not in used and t2[0] != t[0]:
                pairs.append((t, t2))
                used.add(t[0]); used.add(t2[0])
                break
        if len(pairs) == 10: break
    return pairs

def create_next_matchday(app):
    """Create next matchday for each league with staggered individual kickoffs."""
    with app.app_context():
        conn = _db()
        try:
            # Use Kenya time (UTC+3)
            now = _get_eat_time()
            base_offset = random.randint(2, 5)  # Start in 2-5 minutes

            for league_key in LEAGUES:
                row = _q(conn,
                    "SELECT MAX(matchday_number) as mn FROM matchdays WHERE league=?",
                    (league_key,))
                next_num = (row[0]['mn'] or 0) + 1 if row else 1
                league_base = now + timedelta(minutes=base_offset + random.randint(0,3))
                starts_at = league_base.strftime('%Y-%m-%d %H:%M:%S')

                md_id = _ex(conn,
                    "INSERT INTO matchdays (matchday_number, league, starts_at) VALUES (?,?,?)",
                    (next_num, league_key, starts_at))

                pairs = make_pairs(league_key)
                offset = 2  # First match in 2 minutes
                for (hcode, hname), (acode, aname) in pairs:
                    kickoff_dt = league_base + timedelta(minutes=offset)
                    kickoff_str = kickoff_dt.strftime('%Y-%m-%d %H:%M:%S')
                    odds = generate_odds(hcode, acode)
                    _ex(conn,
                        """INSERT INTO matches
                           (matchday_id,home_code,away_code,home_team,away_team,
                            league,odds_json,kickoff_time,preset_home,preset_away)
                           VALUES (?,?,?,?,?,?,?,?,?,?)""",
                        (md_id, hcode, acode, hname, aname,
                         league_key, json.dumps(odds), kickoff_str, None, None))
                    offset += random.randint(3, 8)  # Stagger by 3-8 minutes
        finally:
            conn.close()

# ── Goal event builder ─────────────────────────────────────────────────────
def build_goal_events(home_code, away_code, home_team, away_team,
                      target_home, target_away):
    total = target_home + target_away
    if total == 0:
        return []
    pool = list(range(3, 90))
    random.shuffle(pool)
    all_mins = sorted(pool[:min(total, 87)])
    sides = ['home'] * target_home + ['away'] * target_away
    random.shuffle(sides)
    events = []
    for i, minute in enumerate(all_mins):
        side = sides[i]
        team = home_team if side == 'home' else away_team
        code = home_code if side == 'home' else away_code
        player = get_player(code)
        events.append({
            'minute': minute, 'type': 'goal', 'side': side,
            'desc': f'GOAL! {player} scores for {team}!', 'team': team
        })
    return events

def build_other_events(home_team, away_team, home_code, away_code):
    events = []
    for m in sorted(random.sample(range(2,90), random.randint(6,14))):
        team = random.choice([home_team, away_team])
        events.append({'minute':m,'type':'corner','desc':f'Corner for {team}','team':team})
    for m in sorted(random.sample(range(5,90), random.randint(2,6))):
        team = random.choice([home_team, away_team])
        code = home_code if team == home_team else away_code
        player = get_player(code)
        events.append({'minute':m,'type':'yellow_card',
                       'desc':f'Yellow card: {player} ({team})','team':team})
    if random.random() < 0.10:
        m = random.randint(35, 88)
        team = random.choice([home_team, away_team])
        code = home_code if team == home_team else away_code
        player = get_player(code)
        events.append({'minute':m,'type':'red_card',
                       'desc':f'Red card! {player} sent off!','team':team})
    return events

# ── Bet settlement ─────────────────────────────────────────────────────────
def _settle(conn, match_id, hs, as_, ht_h, ht_a):
    sels = _q(conn,
        "SELECT * FROM bet_selections WHERE match_id=? AND result='pending'",
        (match_id,))
    for sel in sels:
        won = _eval(sel['market'], sel['selection'], hs, as_, ht_h, ht_a)
        _ex(conn,
            "UPDATE bet_selections SET result=? WHERE id=?",
            ('won' if won else 'lost', sel['id']))
    
    for bid in set(s['bet_id'] for s in sels):
        all_s = _q(conn, "SELECT result FROM bet_selections WHERE bet_id=?", (bid,))
        if any(s['result'] == 'pending' for s in all_s):
            continue
        bet = _q(conn, "SELECT * FROM bets WHERE id=?", (bid,))
        if not bet:
            continue
        bet = bet[0]
        if all(s['result'] == 'won' for s in all_s):
            _ex(conn, "UPDATE bets SET status='won',settled_at=datetime('now') WHERE id=?", (bid,))
            _ex(conn, "UPDATE users SET balance=balance+? WHERE id=?",
                (bet['potential_win'], bet['user_id']))
            _ex(conn,
                "INSERT INTO transactions (user_id,type,amount,status,note) VALUES (?,?,?,?,?)",
                (bet['user_id'], 'winnings', bet['potential_win'], 'confirmed', f'Bet #{bid} won'))
        else:
            _ex(conn, "UPDATE bets SET status='lost',settled_at=datetime('now') WHERE id=?", (bid,))

def _eval(market, selection, hs, as_, ht_h, ht_a):
    total = hs + as_
    if market == '1x2':
        return {'1': hs > as_, 'X': hs == as_, '2': as_ > hs}.get(selection, False)
    elif market == 'ou':
        line = float(selection.split('_')[1])
        return (total > line) if selection.startswith('over') else (total < line)
    elif market == 'btts':
        scored = hs > 0 and as_ > 0
        return scored if selection == 'yes' else not scored
    elif market == 'dc':
        return {'1X': hs >= as_, 'X2': as_ >= hs, '12': hs != as_}.get(selection, False)
    elif market == 'htft':
        ht = '1' if ht_h > ht_a else ('X' if ht_h == ht_a else '2')
        ft = '1' if hs > as_ else ('X' if hs == as_ else '2')
        return selection == f'{ht}/{ft}'
    elif market == 'cs':
        return selection == f'{hs}-{as_}'
    return False

# ── Save finished match to history ─────────────────────────────────────────
def _save_to_history(conn, match):
    """Save finished match to history table before deletion"""
    try:
        # Create history table if not exists
        _ex(conn, """
            CREATE TABLE IF NOT EXISTS match_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                match_id INTEGER,
                matchday_id INTEGER,
                league TEXT,
                home_code TEXT,
                away_code TEXT,
                home_team TEXT,
                away_team TEXT,
                home_score INTEGER,
                away_score INTEGER,
                preset_home INTEGER,
                preset_away INTEGER,
                finished_at TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Insert into history
        _ex(conn, """
            INSERT INTO match_history 
            (match_id, matchday_id, league, home_code, away_code, home_team, away_team,
             home_score, away_score, preset_home, preset_away, finished_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            match['id'], match['matchday_id'], match['league'],
            match['home_code'], match['away_code'], match['home_team'], match['away_team'],
            match['home_score'], match['away_score'],
            match['preset_home'], match['preset_away'],
            _now_str()
        ))
    except Exception as e:
        print(f"History save error: {e}")

# ── Clean up old history records (older than 6 hours) ──────────────────────
def _cleanup_old_history(conn):
    """Delete match history older than 6 hours"""
    try:
        eat_tz = ZoneInfo('Africa/Nairobi')
        cutoff_time = (datetime.now(eat_tz) - timedelta(seconds=HISTORY_RETENTION)).strftime('%Y-%m-%d %H:%M:%S')
        _ex(conn, "DELETE FROM match_history WHERE finished_at < ?", (cutoff_time,))
    except Exception as e:
        print(f"History cleanup error: {e}")

# ── Auto-cleanup with history ──────────────────────────────────────────────
def _schedule_cleanup(match_id):
    def do_cleanup():
        time.sleep(CLEANUP_DELAY)
        conn = _db()
        try:
            # Get match data before deleting
            rows = _q(conn, "SELECT * FROM matches WHERE id=?", (match_id,))
            if rows and rows[0]['status'] == 'finished':
                # Save to history
                _save_to_history(conn, rows[0])
                # Delete match data
                _ex(conn, "DELETE FROM match_events WHERE match_id=?", (match_id,))
                _ex(conn, "DELETE FROM matches WHERE id=?", (match_id,))
                print(f"[CLEANUP] Match {match_id} saved to history and deleted")
        except Exception as e:
            print(f"[CLEANUP] Error: {e}")
        finally:
            conn.close()
    t = threading.Thread(target=do_cleanup, daemon=True)
    t.start()

# ── Core 90-minute simulation ──────────────────────────────────────────────
def simulate_match(match_id):
    conn = _db()
    try:
        rows = _q(conn, "SELECT * FROM matches WHERE id=?", (match_id,))
        if not rows:
            return
        m = rows[0]
        home_team = m['home_team']
        away_team = m['away_team']
        home_code = m['home_code']
        away_code = m['away_code']

        # Random scores are generated if no preset score is set
        if m['preset_home'] is not None and m['preset_away'] is not None:
            target_home = int(m['preset_home'])
            target_away = int(m['preset_away'])
        else:
            # Random realistic score
            target_home = random.choices([0,1,2,3,4,5], weights=[15,30,28,15,8,4])[0]
            target_away = random.choices([0,1,2,3,4,5], weights=[18,30,26,14,8,4])[0]

        _ex(conn,
            "UPDATE matches SET status='live',current_minute=0,home_score=0,away_score=0 WHERE id=?",
            (match_id,))
    finally:
        conn.close()

    goal_events = build_goal_events(home_code, away_code, home_team, away_team,
                                     target_home, target_away)
    other_events = build_other_events(home_team, away_team, home_code, away_code)
    all_events = sorted(goal_events + other_events, key=lambda x: x['minute'])
    ev_idx = 0
    home_score = 0
    away_score = 0
    ht_home = 0
    ht_away = 0

    for minute in range(1, 91):
        if not active_simulations.get(match_id, False):
            break

        time.sleep(1)

        conn = _db()
        try:
            rows = _q(conn,
                "SELECT preset_home, preset_away FROM matches WHERE id=?", (match_id,))
            if rows and rows[0]['preset_home'] is not None:
                new_th = int(rows[0]['preset_home'])
                new_ta = int(rows[0]['preset_away'])
                if (new_th, new_ta) != (target_home, target_away):
                    target_home = new_th
                    target_away = new_ta
                    future_others = [e for e in all_events[ev_idx:] if e['type'] != 'goal']
                    rem_h = max(0, target_home - home_score)
                    rem_a = max(0, target_away - away_score)
                    new_goals = build_goal_events(
                        home_code, away_code, home_team, away_team, rem_h, rem_a)
                    mins_left = list(range(minute+1, 90))
                    if new_goals and mins_left:
                        sz = min(len(new_goals), len(mins_left))
                        new_mins = sorted(random.sample(mins_left, sz))
                        for i, g in enumerate(new_goals[:len(new_mins)]):
                            g['minute'] = new_mins[i]
                    remaining = sorted(new_goals + future_others, key=lambda x: x['minute'])
                    all_events = all_events[:ev_idx] + remaining

            while ev_idx < len(all_events) and all_events[ev_idx]['minute'] <= minute:
                ev = all_events[ev_idx]
                _ex(conn,
                    """INSERT INTO match_events
                       (match_id,minute,event_type,description,team,is_home)
                       VALUES (?,?,?,?,?,?)""",
                    (match_id, ev['minute'], ev['type'], ev['desc'],
                     ev['team'], 1 if ev['team'] == home_team else 0))
                if ev['type'] == 'goal':
                    if ev['side'] == 'home':
                        home_score += 1
                    else:
                        away_score += 1
                ev_idx += 1

            if minute == 45:
                ht_home, ht_away = home_score, away_score
                _ex(conn, "UPDATE matches SET ht_home=?,ht_away=? WHERE id=?",
                    (ht_home, ht_away, match_id))

            _ex(conn,
                "UPDATE matches SET current_minute=?,home_score=?,away_score=? WHERE id=?",
                (minute, home_score, away_score, match_id))
        finally:
            conn.close()

    # Full Time
    conn = _db()
    try:
        _ex(conn,
            "UPDATE matches SET status='finished',current_minute=90,home_score=?,away_score=? WHERE id=?",
            (home_score, away_score, match_id))
        _settle(conn, match_id, home_score, away_score, ht_home, ht_away)
    finally:
        conn.close()

    active_simulations.pop(match_id, None)
    _schedule_cleanup(match_id)

# ── Start a single match ───────────────────────────────────────────────────
def _start_match_thread(match_id):
    active_simulations[match_id] = True
    t = threading.Thread(target=simulate_match, args=(match_id,), daemon=True)
    t.start()

# ── Admin helpers ──────────────────────────────────────────────────────────
def admin_set_score(match_id, home, away):
    conn = _db()
    try:
        _ex(conn, "UPDATE matches SET preset_home=?,preset_away=? WHERE id=?",
            (home, away, match_id))
    finally:
        conn.close()

def admin_force_start(match_id):
    conn = _db()
    try:
        rows = _q(conn, "SELECT * FROM matches WHERE id=?", (match_id,))
        if rows and rows[0]['status'] == 'upcoming':
            _ex(conn,
                "UPDATE matches SET status='live',kickoff_time=? WHERE id=?",
                (_now_str(), match_id))
            _ex(conn,
                "UPDATE matchdays SET status='live' WHERE id=? AND status='upcoming'",
                (rows[0]['matchday_id'],))
            _start_match_thread(match_id)
    finally:
        conn.close()

def admin_force_finish(match_id):
    active_simulations[match_id] = False
    time.sleep(1.5)
    conn = _db()
    try:
        rows = _q(conn, "SELECT * FROM matches WHERE id=?", (match_id,))
        if rows:
            m = rows[0]
            _ex(conn, "UPDATE matches SET status='finished',current_minute=90 WHERE id=?", (match_id,))
            _settle(conn, match_id, m['home_score'], m['away_score'], m['ht_home'], m['ht_away'])
            # Schedule cleanup after finishing
            threading.Thread(target=lambda: (time.sleep(CLEANUP_DELAY), _schedule_cleanup(match_id)), daemon=True).start()
    finally:
        conn.close()

# ── Background scheduler ───────────────────────────────────────────────────
def _scheduler_loop(app):
    time.sleep(5)
    while True:
        try:
            conn = _db()
            try:
                # Use Kenya time (UTC+3)
                now_kenya = _get_eat_time()
                now_str = now_kenya.strftime('%Y-%m-%d %H:%M:%S')

                # Clean up old history records (older than 6 hours)
                _cleanup_old_history(conn)

                # Start matches whose kickoff time has arrived
                due = _q(conn,
                    "SELECT * FROM matches WHERE status='upcoming' AND kickoff_time <= ?",
                    (now_str,))
                
                if due:
                    print(f"[SCHEDULER] Found {len(due)} matches to start at {now_str}")
                    for m in due:
                        print(f"[SCHEDULER] Starting match {m['id']}: {m['home_code']} vs {m['away_code']}")
                        _ex(conn, "UPDATE matches SET status='live' WHERE id=?", (m['id'],))
                        _ex(conn,
                            "UPDATE matchdays SET status='live' WHERE id=? AND status='upcoming'",
                            (m['matchday_id'],))
                        _start_match_thread(m['id'])

                # Mark matchdays finished
                live_mds = _q(conn, "SELECT id FROM matchdays WHERE status='live'")
                for md in live_mds:
                    pending = _q(conn,
                        "SELECT COUNT(*) as c FROM matches WHERE matchday_id=? AND status != 'finished'",
                        (md['id'],))
                    if pending and int(pending[0]['c']) == 0:
                        print(f"[SCHEDULER] Matchday {md['id']} finished")
                        _ex(conn, "UPDATE matchdays SET status='finished' WHERE id=?", (md['id'],))

                # Delete finished matchdays with no matches
                finished_mds = _q(conn, "SELECT id FROM matchdays WHERE status='finished'")
                for md in finished_mds:
                    remaining = _q(conn,
                        "SELECT COUNT(*) as c FROM matches WHERE matchday_id=?",
                        (md['id'],))
                    if remaining and int(remaining[0]['c']) == 0:
                        print(f"[SCHEDULER] Cleaning up matchday {md['id']}")
                        _ex(conn, "DELETE FROM matchdays WHERE id=?", (md['id'],))

                # Ensure upcoming matchdays
                upcoming = _q(conn, "SELECT COUNT(*) as c FROM matchdays WHERE status='upcoming'")
                upcoming_count = int(upcoming[0]['c']) if upcoming else 0

            finally:
                conn.close()

            if upcoming_count < 2:
                print("[SCHEDULER] Creating new matchdays...")
                with app.app_context():
                    create_next_matchday(app)

        except Exception as e:
            print(f"[SCHEDULER] Error: {e}")
            import traceback
            traceback.print_exc()

        time.sleep(10)  # Check every 10 seconds

def start_scheduler(app):
    t = threading.Thread(target=_scheduler_loop, args=(app,), daemon=True)
    t.start()
