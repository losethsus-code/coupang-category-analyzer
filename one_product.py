"""One-product sourcing sprint. Pure stdlib; preserves all existing SQLite tables.

Goal: make a sample/no-go decision in 72h, not build an exhaustive market database.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

ACTIVE = ('발굴', '시장확인', '제조문의', '샘플결정')
FINISHED = ('샘플주문', '보류', '탈락')
ALL_STATES = ACTIVE + FINISHED


def _time() -> datetime:
    return datetime.now(timezone.utc)


def setup(conn: sqlite3.Connection) -> None:
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS one_product_candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            keyword TEXT NOT NULL,
            problem TEXT NOT NULL DEFAULT '',
            difference TEXT NOT NULL DEFAULT '',
            manufacturer_note TEXT NOT NULL DEFAULT '',
            market_note TEXT NOT NULL DEFAULT '',
            state TEXT NOT NULL DEFAULT '발굴',
            checks_cert INTEGER NOT NULL DEFAULT 0,
            checks_cost INTEGER NOT NULL DEFAULT 0,
            checks_shipping INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            deadline_at TEXT NOT NULL,
            decided_at TEXT,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_one_product_state ON one_product_candidates(state,updated_at);
    ''')
    conn.commit()


def current(conn: sqlite3.Connection) -> dict | None:
    setup(conn)
    placeholders = ','.join('?' for _ in ACTIVE)
    found = conn.execute(
        f'SELECT * FROM one_product_candidates WHERE state IN ({placeholders}) ORDER BY id DESC LIMIT 1',
        ACTIVE,
    ).fetchone()
    return dict(found) if found else None


def latest_history(conn: sqlite3.Connection, limit: int = 10) -> list[dict]:
    setup(conn)
    return [dict(r) for r in conn.execute(
        'SELECT * FROM one_product_candidates ORDER BY id DESC LIMIT ?', (limit,),
    ).fetchall()]


def start(conn: sqlite3.Connection, keyword: str, problem: str = '', difference: str = '') -> dict:
    setup(conn)
    keyword = ' '.join(keyword.split()).strip()
    if not keyword or len(keyword) > 80:
        raise ValueError('메인키워드를 1~80자로 입력하세요.')
    if current(conn):
        raise ValueError('진행 중인 상품 1개가 있습니다. 먼저 샘플·보류·탈락을 결정하세요.')
    now = _time()
    conn.execute('''INSERT INTO one_product_candidates
       (keyword,problem,difference,created_at,deadline_at,updated_at)
       VALUES (?,?,?,?,?,?)''',
       (keyword,problem[:1200],difference[:1200],now.isoformat(),
        (now+timedelta(hours=72)).isoformat(),now.isoformat()))
    conn.commit()
    return current(conn)


def update_notes(conn: sqlite3.Connection, candidate_id: int, *, problem: str,
                 difference: str, market_note: str, manufacturer_note: str,
                 checks_cert: bool, checks_cost: bool, checks_shipping: bool) -> dict:
    setup(conn)
    c = conn.execute('SELECT * FROM one_product_candidates WHERE id=?', (candidate_id,)).fetchone()
    if not c or c['state'] not in ACTIVE:
        raise ValueError('진행 중인 상품만 수정할 수 있습니다.')
    conn.execute('''UPDATE one_product_candidates SET
        problem=?,difference=?,market_note=?,manufacturer_note=?,
        checks_cert=?,checks_cost=?,checks_shipping=?,updated_at=? WHERE id=?''',
        (problem[:1200],difference[:1200],market_note[:1200],manufacturer_note[:1200],
         int(checks_cert),int(checks_cost),int(checks_shipping),_time().isoformat(),candidate_id))
    conn.commit()
    return dict(conn.execute('SELECT * FROM one_product_candidates WHERE id=?', (candidate_id,)).fetchone())


def advance(conn: sqlite3.Connection, candidate_id: int, new_state: str) -> dict:
    setup(conn)
    if new_state not in ALL_STATES:
        raise ValueError('알 수 없는 진행상태입니다.')
    c = conn.execute('SELECT * FROM one_product_candidates WHERE id=?',(candidate_id,)).fetchone()
    if c is None or c['state'] not in ACTIVE:
        raise ValueError('종료된 후보는 다시 변경하지 않습니다.')
    if new_state == '샘플주문' and not (c['checks_cert'] and c['checks_cost'] and c['checks_shipping']):
        raise ValueError('샘플 주문 전 인증·원가·부피 확인이 필요합니다.')
    now=_time().isoformat()
    decided=now if new_state in FINISHED else None
    conn.execute('UPDATE one_product_candidates SET state=?,decided_at=?,updated_at=? WHERE id=?',
                 (new_state,decided,now,candidate_id))
    conn.commit()
    return dict(conn.execute('SELECT * FROM one_product_candidates WHERE id=?', (candidate_id,)).fetchone())


def deadline_display(candidate: dict, now: datetime | None = None) -> tuple[str, bool]:
    now = now or _time()
    due = datetime.fromisoformat(candidate['deadline_at'])
    remaining = due-now
    if remaining.total_seconds() <= 0:
        return '72시간 경과 · 오늘 결정 필요', True
    hours = int(remaining.total_seconds()//3600)
    return f'결정까지 {hours}시간 남음', False


def market_snapshot(conn: sqlite3.Connection, keyword: str) -> dict | None:
    r=conn.execute('''SELECT first_page_revenue,monthly_search,top10_reviews,measured_at,
        source FROM markets WHERE keyword=? ORDER BY measured_at DESC LIMIT 1''', (keyword,)).fetchone()
    return dict(r) if r else None
