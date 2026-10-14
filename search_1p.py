"""쿠팡 검색 1페이지 검증: URL 생성과 사용자 제공 합법적 자료 분석 전용.

검색결과 페이지를 요청하거나 스크래핑/우회하지 않는다.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from statistics import median
from typing import Any
from urllib.parse import quote

from core import compact, normalize, num, product_group

SEARCH_URL = 'https://www.coupang.com/np/search?q='


def search_url(keyword: str) -> str:
    word=normalize(keyword)
    if not word or len(word)>80 or '\n' in word:
        raise ValueError('검색어는 1~80자여야 합니다.')
    return SEARCH_URL + quote(word, safe='')


def setup(conn: sqlite3.Connection) -> None:
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS search_jobs (
      keyword TEXT PRIMARY KEY, state TEXT NOT NULL DEFAULT '검증 대기',
      priority INTEGER NOT NULL DEFAULT 0, memo TEXT NOT NULL DEFAULT '',
      updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS search_snapshots (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      keyword TEXT NOT NULL, captured_at TEXT NOT NULL,
      source TEXT NOT NULL, completeness TEXT NOT NULL,
      rows_count INTEGER NOT NULL, unique_count INTEGER NOT NULL,
      fingerprint TEXT DEFAULT '', UNIQUE(keyword,captured_at,source)
    );
    CREATE TABLE IF NOT EXISTS search_products (
      snapshot_id INTEGER NOT NULL, rank INTEGER NOT NULL,
      product_id TEXT DEFAULT '', title TEXT NOT NULL,
      price INTEGER, reviews INTEGER, delivery TEXT DEFAULT '',
      estimated_sales INTEGER, estimated_revenue INTEGER,
      url TEXT DEFAULT '', PRIMARY KEY(snapshot_id,rank),
      FOREIGN KEY(snapshot_id) REFERENCES search_snapshots(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_search_snapshots_keyword ON search_snapshots(keyword,captured_at);
    ''')
    existing={r[1] for r in conn.execute('PRAGMA table_info(search_snapshots)').fetchall()}
    if 'fingerprint' not in existing:
        conn.execute("ALTER TABLE search_snapshots ADD COLUMN fingerprint TEXT DEFAULT ''")
    conn.commit()


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def queue_keywords(conn: sqlite3.Connection, words: list[str]) -> int:
    setup(conn)
    added=0
    for raw in words:
        keyword=normalize(raw)
        if not keyword or len(keyword)>80: continue
        cur=conn.execute('INSERT OR IGNORE INTO search_jobs(keyword,state,updated_at) VALUES(?,?,?)',
            (keyword,'검증 대기',now()))
        added+=cur.rowcount
    conn.commit()
    return added


def set_job_state(conn: sqlite3.Connection, keyword: str, state: str, memo: str='') -> None:
    valid={'검증 대기','검증 진행','심층검증','1차 통과','보류','탈락','완료'}
    if state not in valid: raise ValueError(f'사용할 수 없는 상태: {state}')
    queue_keywords(conn,[keyword])
    conn.execute('UPDATE search_jobs SET state=?,memo=?,updated_at=? WHERE keyword=?',
        (state,memo[:1000],now(),normalize(keyword)))
    conn.commit()


def queue_rows(conn: sqlite3.Connection) -> list[dict]:
    setup(conn)
    rows=[]
    for record in conn.execute('SELECT * FROM search_jobs ORDER BY priority DESC,keyword'):
        row=dict(record)
        row['search_url']=search_url(row['keyword'])
        market=conn.execute('SELECT * FROM markets WHERE keyword=? ORDER BY measured_at DESC LIMIT 1',(row['keyword'],)).fetchone()
        if market:
            row['market_revenue']=market['first_page_revenue']
            row['monthly_search']=market['monthly_search']
            row['top10_reviews']=market['top10_reviews']
            row['market_date']=market['measured_at']
        snapshot=latest_snapshot(conn,row['keyword'])
        row['product_rows']=snapshot['rows_count'] if snapshot else 0
        rows.append(row)
    return rows


def _cell(row: dict, *aliases: str) -> Any:
    lookup={compact(k):v for k,v in row.items() if k is not None}
    for name in aliases:
        if compact(name) in lookup:return lookup[compact(name)]
    return None


def parse_search_rows(rows: list[dict], default_keyword: str='') -> tuple[list[dict],list[str]]:
    """CSV 등 외부에서 사용자가 제공한 1페이지 데이터의 필드만 정규화."""
    parsed=[]; errors=[]
    for line,raw in enumerate(rows,2):
        kw=normalize(_cell(raw,'keyword','메인키워드','검색어') or default_keyword)
        rank=num(_cell(raw,'rank','순위','랭킹'))
        title=normalize(_cell(raw,'title','상품명','name','product_name'))
        if not kw or not title or rank is None or not (1<=rank<=100):
            errors.append(f'{line}행: 키워드·상품명 또는 1~100위 순위 누락');continue
        parsed.append({'keyword':kw,'rank':rank,'title':title,
            'product_id':normalize(_cell(raw,'product_id','상품ID','productId')),
            'price':num(_cell(raw,'price','판매가','가격')),
            'reviews':num(_cell(raw,'reviews','리뷰수','리뷰','review_count')),
            'delivery':normalize(_cell(raw,'delivery','배송방식','배송')),
            'estimated_sales':num(_cell(raw,'estimated_sales','월판매량','판매량','wingStat.salesLast28d')),
            'estimated_revenue':num(_cell(raw,'estimated_revenue','월매출','매출','wingStat.monthlyRevenue')),
            'url':normalize(_cell(raw,'url','상품URL','상품링크'))})
    return parsed,errors


def parse_bulsaja_products(payload: Any) -> tuple[list[dict],list[str]]:
    """기존 v0.6 사용자 소유 수집 JSON의 agGrids[...].rows[].cells 가공.
    판매량/매출 숫자도 해당 서비스의 추정치로만 취급한다.
    """
    records=payload.get('records',[]) if isinstance(payload,dict) else payload
    if not isinstance(records,list): raise ValueError('records 배열을 확인할 수 없습니다.')
    rows=[]; warnings=[]
    for item in records:
        keyword=normalize(item.get('keyword'))
        for grid in item.get('agGrids',[]) or []:
            for raw in grid.get('rows',[]) or []:
                cells=raw.get('cells',{})
                if not isinstance(cells,dict):continue
                def t(key):
                    c=cells.get(key,{})
                    return c.get('text','') if isinstance(c,dict) else str(c or '')
                rank=num(t('rank')); title=normalize(t('title'))
                if not rank or rank>100 or not title:continue
                delivery=t('deliveryType')
                if not delivery:
                    imgs=(cells.get('deliveryType',{}) or {}).get('images',[])
                    delivery=' '.join(str(z.get('alt','')) for z in imgs if isinstance(z,dict))
                rows.append({'keyword':keyword,'rank':rank,'title':title,
                    'price':num(t('price')),'reviews':num(t('review')),
                    'estimated_sales':num(t('wingStat.salesLast28d')),
                    'estimated_revenue':num(t('wingStat.monthlyRevenue')),
                    'product_id':'','delivery':delivery,'url':''})
    if not rows:warnings.append('JSON에 agGrids.rows.cells 상품 목록이 없거나 순위·상품명이 없습니다. 요약 데이터만 가져올 수 있습니다.')
    return rows,warnings


def _group_id(row: dict) -> str:
    # 제품 ID를 확인할 수 있으면 ID 우선, 아니면 보수적 제목 표준화.
    return product_group(row)


def save_search_rows(conn: sqlite3.Connection, records: list[dict], source: str='사용자 제공 CSV',
                     captured_at: str | None=None) -> dict:
    setup(conn)
    stamped=captured_at or now()
    bykeyword=defaultdict(list)
    for row in records:
        kw=normalize(row.get('keyword'))
        if kw:bykeyword[kw].append(row)
    added=[]; warnings=[]; unchanged=[]
    for kw,items in bykeyword.items():
        unique_ranks=set(); accepted=[]
        for row in sorted(items,key=lambda r:r['rank']):
            rank=row['rank']
            if rank in unique_ranks:
                warnings.append(f'{kw}: 중복 순위 {rank}위 생략');continue
            unique_ranks.add(rank);accepted.append(row)
        groups={_group_id(r) for r in accepted}
        stable=[{k:r.get(k) for k in ('rank','product_id','title','price','reviews','delivery','estimated_sales','estimated_revenue','url')} for r in accepted]
        fingerprint=hashlib.sha256(json.dumps(stable,sort_keys=True,ensure_ascii=False).encode('utf-8')).hexdigest()
        prior=conn.execute('SELECT id FROM search_snapshots WHERE keyword=? AND source=? AND fingerprint=? ORDER BY id DESC LIMIT 1',
                           (kw,source,fingerprint)).fetchone()
        if prior:
            unchanged.append(kw)
            queue_keywords(conn,[kw])
            continue
        completeness='40위 표본' if len(accepted)>=40 and all(i in unique_ranks for i in range(1,41)) else '일부 순위 표본'
        cur=conn.execute('''INSERT INTO search_snapshots(keyword,captured_at,source,completeness,rows_count,unique_count,fingerprint)
            VALUES(?,?,?,?,?,?,?)''',(kw,stamped,source,completeness,len(accepted),len(groups),fingerprint))
        sid=cur.lastrowid
        for row in accepted:
            conn.execute('''INSERT INTO search_products(snapshot_id,rank,product_id,title,price,reviews,delivery,estimated_sales,estimated_revenue,url)
                VALUES(?,?,?,?,?,?,?,?,?,?)''',
                (sid,row['rank'],row.get('product_id',''),row['title'],row.get('price'),row.get('reviews'),
                row.get('delivery',''),row.get('estimated_sales'),row.get('estimated_revenue'),row.get('url','')))
        queue_keywords(conn,[kw])
        added.append({'keyword':kw,'count':len(accepted),'unique':len(groups),'snapshot_id':sid})
    conn.commit()
    return {'snapshots':added,'warnings':warnings,'unchanged':unchanged}


def latest_snapshot(conn: sqlite3.Connection, keyword: str) -> dict | None:
    setup(conn)
    row=conn.execute('''SELECT * FROM search_snapshots WHERE keyword=? ORDER BY captured_at DESC,id DESC LIMIT 1''',(keyword,)).fetchone()
    return dict(row) if row else None


def latest_search_products(conn: sqlite3.Connection, keyword: str) -> list[dict]:
    snap=latest_snapshot(conn,keyword)
    if snap is None:return []
    return [dict(r) for r in conn.execute('SELECT * FROM search_products WHERE snapshot_id=? ORDER BY rank',(snap['id'],))]


def evaluate_keyword(conn: sqlite3.Connection, keyword: str) -> dict:
    """검색 결과와 불사자 요약을 명확히 구분. 매출 모르면 시장 통과 주장 안 함."""
    rows=latest_search_products(conn,keyword)
    market=conn.execute('SELECT * FROM markets WHERE keyword=? ORDER BY measured_at DESC LIMIT 1',(keyword,)).fetchone()
    prices=[x['price'] for x in rows if x['price'] is not None]
    reviews=[x['reviews'] for x in rows if x['reviews'] is not None]
    top10=[x for x in rows if x['rank']<=10]
    top10rev=[x['reviews'] for x in top10 if x['reviews'] is not None]
    grp=set(_group_id(r) for r in rows)
    lowrev_examples=[x for x in rows if x['reviews'] is not None and x['reviews']<=300 and x['rank']<=20]
    mid=[x for x in rows if 5<=x['rank']<=10]
    sales_mid=sum((x['estimated_sales'] or 0) for x in mid) if any(x['estimated_sales'] is not None for x in mid) else None
    revenue=int(market['first_page_revenue']) if market and market['first_page_revenue'] is not None else None
    market_state='미측정' if revenue is None else ('3억 이상' if revenue>=300_000_000 else '3억 미만')
    risk=[]
    if market and revenue is not None and revenue>=300_000_000: risk.append('시장규모 3억+ (추정)')
    if len(rows)<40:risk.append('검색 1페이지 표본 미완성')
    if len(top10rev)<8:risk.append('TOP10 리뷰 데이터 부족')
    if revenue is None:risk.append('불사자 시장매출 미확인')
    return {'keyword':keyword,'market_revenue':revenue,'market_state':market_state,
            'monthly_search':market['monthly_search'] if market else None,
            'top10_reviews_bulsaja':market['top10_reviews'] if market else None,
            'top10_reviews_sample':round(sum(top10rev)/len(top10rev)) if top10rev else None,
            'seller_rocket_pct':market['seller_rocket_pct'] if market else None,
            'rows':len(rows),'unique_products':len(grp),'low_review_top20':len(lowrev_examples),
            'median_price':int(median(prices)) if prices else None,
            'price_band_ratio':sum(15000<=p<=30000 for p in prices)/len(prices) if prices else None,
            'mid_rank_sales_sum':sales_mid,
            'mid_rank_sales_is_deduped':False,
            'issues':risk,'low_review_examples':lowrev_examples[:6],
            'status':'추가 검증 필요' if revenue is None or len(rows)<40 else '시장 검증 후보',
            'search_url':search_url(keyword)}
