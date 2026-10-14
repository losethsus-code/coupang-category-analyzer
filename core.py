"""쿠팡 소싱 탐색기 분석 코어. 표준 라이브러리만 필요. 타 사이트 자동 수집 기능 없음."""
from __future__ import annotations

import csv
import io
import json
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / 'app_data' / 'sourcing.db'
PRICE_MIN = 15000
PRICE_MAX = 30000
MAX_RANK = 40

# 카테고리 이름으로 판정할 수 있는 확실한 위험만 제외한다. 혼재/불명확하면 조건부.
CERT_HINTS = ('전기', '전자', '배터리', '충전', '전열', '가열', '온열', '의료기기', '건강기기', '살충제', '화학약품', '가습기', '제습기', '공기청정', '히터', '전동', '유아용 안전', '가정용 소독', '세정제', '세탁세제')
BULKY_HINTS = ('대형가구', '침대', '매트리스', '소파', '장롱', '옷장', '냉장고', '세탁기', '책상', '식탁', '의자', '대형 수납장', '붙박이', '대형 행거', '쇼파')
SEASON_HINTS = ('크리스마스', '트리 장식', '물놀이', '튜브', '여름휴가', '스키', '스노보드', '방한', '겨울난방')
MIXED_HINTS = ('선반', '진열대', '행거', '수납장', '신발장', '신발정리대', '주방수납', '정리선반', '카트', '거치대', '욕실선반', '대용량', '박스', '이동식')
SAFE_HINTS = ('정리함', '정리대', '파우치', '보관함', '브러쉬', '화장품', '서랍 정리', '케이블 정리', '소품', '걸이', '미니 수납')
# 상품명에서 표제어를 찾기 위한 초기 사전. 향후 대시보드에서 편집 가능.
KEYWORD_ALIASES = {
    '화장품정리함': ['화장품 정리함','화장품정리함','메이크업 정리함','메이크업정리함','화장대 정리함','화장대정리함'],
    '신발정리대': ['신발정리대','신발 정리대','슈즈랙','신발 수납 선반'],
    '슬리퍼거치대': ['슬리퍼거치대','슬리퍼 거치대','슬리퍼걸이','슬리퍼 걸이','실내화 거치대'],
    '문걸이수납선반': ['문걸이 수납선반','문걸이 선반','도어후크 선반','문걸이수납선반'],
    '브러쉬정리함': ['브러쉬 정리함','브러시 정리함','브러쉬정리함'],
    '미니신발장': ['미니 신발장','미니신발장'],
    '주방정리선반': ['주방 정리선반','주방정리선반','주방 수납선반'],
    '북카트': ['북카트','북 카트','책 카트'],
    '피규어진열장': ['피규어 진열장','피규어진열장','피규어 장식장'],
    '서랍정리함': ['서랍 정리함','서랍정리함','칸막이 정리함'],
    '수납박스': ['수납 박스','수납박스','리빙박스','리빙 박스'],
    '모자거치대': ['모자거치대','모자 거치대','모자걸이'],
    '의자팔걸이쿠션': ['팔걸이 쿠션','의자 팔걸이 쿠션'],
}


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def connection(db_path: str | Path = DB_PATH) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA foreign_keys=ON')
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS categories (
          code TEXT PRIMARY KEY, parent_code TEXT, category_name TEXT NOT NULL,
          path TEXT NOT NULL, depth INTEGER, is_leaf INTEGER NOT NULL,
          api_status TEXT DEFAULT '', fit TEXT DEFAULT '조건부', reason TEXT DEFAULT '',
          overridden INTEGER DEFAULT 0, source TEXT DEFAULT '', updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS products (
          category_code TEXT NOT NULL, rank INTEGER NOT NULL, product_id TEXT DEFAULT '',
          title TEXT NOT NULL, price INTEGER, reviews INTEGER, brand TEXT DEFAULT '',
          delivery TEXT DEFAULT '', url TEXT DEFAULT '', snapshot_at TEXT NOT NULL,
          PRIMARY KEY (category_code,rank,snapshot_at)
        );
        CREATE TABLE IF NOT EXISTS scans (
          category_code TEXT PRIMARY KEY, state TEXT NOT NULL, row_count INTEGER DEFAULT 0,
          message TEXT DEFAULT '', updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS keywords (
          category_code TEXT NOT NULL, keyword TEXT NOT NULL,
          product_count INTEGER NOT NULL DEFAULT 0, sample_titles TEXT DEFAULT '',
          status TEXT DEFAULT '검증 대기', updated_at TEXT NOT NULL,
          PRIMARY KEY(category_code, keyword)
        );
        CREATE TABLE IF NOT EXISTS markets (
          keyword TEXT NOT NULL, measured_at TEXT NOT NULL,
          first_page_revenue INTEGER, monthly_search INTEGER, top10_reviews INTEGER,
          seller_rocket_pct REAL, note TEXT DEFAULT '', source TEXT DEFAULT '',
          PRIMARY KEY(keyword,measured_at)
        );
        CREATE TABLE IF NOT EXISTS job_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
          event TEXT NOT NULL, detail TEXT NOT NULL DEFAULT ''
        );
    ''')
    conn.commit()
    return conn


def event(conn: sqlite3.Connection, action: str, detail: str = '') -> None:
    conn.execute('INSERT INTO job_events(created_at,event,detail) VALUES (?,?,?)', (utcnow(),action,detail[:1000]))
    conn.commit()


def normalize(s: Any) -> str:
    return re.sub(r'\s+', ' ', str(s or '')).strip()


def compact(s: Any) -> str:
    return re.sub(r'[^0-9a-z가-힣]', '', normalize(s).lower())


def category_fit(path: str, name: str | None = None) -> tuple[str,str]:
    """규제/부피 여부 추정. 인증이 필요 없다고 법적으로 확정하지 않음."""
    target = normalize(name or str(path).split(' > ')[-1])
    path = normalize(path)
    if any(x in target for x in CERT_HINTS):
        return '제외', '규제·인증 가능성이 높은 품목군(카테고리명 기준 잠정 분류)'
    if any(x in target for x in BULKY_HINTS):
        return '제외', '대형·고부피 상품 중심일 가능성(카테고리명 기준)'
    if any(x in target for x in SEASON_HINTS):
        return '제외', '시즌성이 강할 가능성'
    if any(compact(x) in compact(target) for x in MIXED_HINTS):
        return '조건부', '소형·대형 또는 규격이 혼재할 가능성; 자료 확인 후 판단'
    if any(x in target for x in SAFE_HINTS):
        return '적합', '소형 생활잡화 중심 가능성; 실제 제품별 인증·포장 규격 확인 필요'
    return '조건부', '카테고리명만으로 인증·부피 여부를 확정할 수 없음'


def flatten_tree(payload: Any, root_keyword: str='생활용품') -> list[dict]:
    """쿠팡 공식 RFM API JSON {data:{name,child:[...]}} 또는 중첩 노드 배열 지원."""
    if isinstance(payload, dict) and 'data' in payload:
        payload = payload['data']
    if isinstance(payload, dict):
        nodes = [payload]
    elif isinstance(payload, list):
        nodes = payload
    else:
        raise ValueError('카테고리 JSON은 data 객체 또는 노드 배열이어야 합니다.')
    results: list[dict] = []
    used: set[str] = set()
    def walk(node: dict, parents: list[tuple[str,str]], matched: bool) -> None:
        name = normalize(node.get('name') or node.get('categoryName'))
        code = str(node.get('displayItemCategoryCode') or node.get('displayCategoryCode') or node.get('code') or '')
        child = node.get('child') or node.get('children') or []
        if not isinstance(child, list): child=[]
        if not name: return
        root = name in ('ROOT','Root','전체','ALL')
        in_scope = matched or (compact(root_keyword) in compact(name))
        chain = parents if root else (parents + [(code,name)])
        if in_scope and not root and code and code not in used:
            used.add(code)
            fit, reason = category_fit(' > '.join(x[1] for x in chain), name)
            results.append({'code':code,'parent_code': parents[-1][0] if parents else '',
                'name':name,'path':' > '.join(x[1] for x in chain),'depth':len(chain),
                'is_leaf':not bool(child),'api_status':normalize(node.get('status','ACTIVE')),
                'fit':fit, 'reason':reason, 'source':'공식 RFM API JSON'})
        for sub in child:
            if isinstance(sub,dict):walk(sub,chain,in_scope)
    for item in nodes:
        if isinstance(item,dict): walk(item, [], False)
    return results


def _lookup(row: dict, *names: str) -> str:
    normalized = {compact(k): v for k,v in row.items() if k is not None}
    for name in names:
        k=compact(name)
        if k in normalized and normalized[k] is not None:return normalize(normalized[k])
    return ''


def parse_category_rows(rows: list[dict]) -> list[dict]:
    """수동 카테고리 CSV/엑셀에서 헤더 기반으로 트리 복원. 실제 leaf는 하위경로 존재로 검증."""
    parsed=[]
    seen=set()
    for idx,row in enumerate(rows,1):
        names=[_lookup(row,'1차 카테고리','대카테고리','1차','카테고리1','category1','depth1','level1'),
            _lookup(row,'2차 카테고리','중카테고리','2차','카테고리2','category2','depth2','level2'),
            _lookup(row,'3차 카테고리','소카테고리','3차','카테고리3','category3','depth3','level3'),
            _lookup(row,'4차 카테고리','세카테고리','4차','카테고리4','category4','depth4','level4'),
            _lookup(row,'5차 카테고리','5차','카테고리5','category5','depth5','level5')]
        names=[n for n in names if n]
        rawpath=_lookup(row,'카테고리 경로','전체경로','카테고리명경로','path','categorypath')
        if not names and rawpath:
            names=[x.strip() for x in re.split(r'\s*(?:>|/|≫)\s*',rawpath) if x.strip()]
        if not names:
            short=_lookup(row,'카테고리명','name')
            if short: names=['생활용품',short]
        if not names or '생활용품' not in names[0] and not any('생활용품' in x for x in names):continue
        code=_lookup(row,'카테고리ID','카테고리 코드','노출카테고리코드','displayCategoryCode','displayItemCategoryCode','category_id','category_code','code')
        if not code: code=f'PATH-{compact(" > ".join(names))}'
        if code in seen: continue
        seen.add(code)
        fit,reason=category_fit(' > '.join(names),names[-1])
        parsed.append({'code':code,'parent_code':'','name':names[-1],
            'path':' > '.join(names),'depth':len(names),'is_leaf':True,'api_status':_lookup(row,'상태','status') or '미확인',
            'fit':fit,'reason':reason,'source':'공식/수동 카테고리 CSV·Excel'})
    paths=[x['path'] for x in parsed]
    for x in parsed:
        x['is_leaf']=not any(z.startswith(x['path']+' > ') for z in paths)
    return parsed


def save_categories(conn: sqlite3.Connection, rows: list[dict]) -> tuple[int,int]:
    count=0; skipped=0
    for x in rows:
        if x['api_status'] in ('DISABLED','READY'):
            skipped += 1; continue
        old=conn.execute('SELECT fit,reason,overridden FROM categories WHERE code=?',(x['code'],)).fetchone()
        fit=old['fit'] if old and old['overridden'] else x['fit']
        reason=old['reason'] if old and old['overridden'] else x['reason']
        override=old['overridden'] if old else 0
        conn.execute('''INSERT INTO categories(code,parent_code,category_name,path,depth,is_leaf,api_status,fit,reason,overridden,source,updated_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(code) DO UPDATE SET
        parent_code=excluded.parent_code,category_name=excluded.category_name,path=excluded.path,
        depth=excluded.depth,is_leaf=excluded.is_leaf,api_status=excluded.api_status,
        fit=excluded.fit,reason=excluded.reason,overridden=excluded.overridden,
        source=excluded.source,updated_at=excluded.updated_at''',
        (x['code'],x['parent_code'],x['name'],x['path'],x['depth'],int(x['is_leaf']),x['api_status'],fit,reason,override,x['source'],utcnow()))
        count+=1
    conn.commit()
    event(conn,'카테고리 가져오기',f'저장 {count}, 비활성 제외 {skipped}')
    return count,skipped


def set_category_fit(conn, code: str, fit: str, reason: str) -> None:
    if fit not in ('적합','조건부','제외'):raise ValueError('알 수 없는 상태')
    conn.execute('UPDATE categories SET fit=?,reason=?,overridden=1,updated_at=? WHERE code=?',(fit,reason,utcnow(),code))
    conn.commit()
    event(conn,'카테고리 판정 변경',f'{code}: {fit} {reason}')


def num(value: Any) -> int | None:
    if value is None or str(value).strip()=='': return None
    s=re.sub(r'[,원개회\s]','',str(value))
    try: return int(float(s))
    except ValueError:return None


def parse_csv_bytes(filebytes: bytes) -> list[dict]:
    for encoding in ('utf-8-sig','cp949','euc-kr'):
        try: return [dict(row) for row in csv.DictReader(io.StringIO(filebytes.decode(encoding)))]
        except UnicodeError:continue
    raise ValueError('CSV는 UTF-8 또는 CP949 인코딩으로 저장해 주세요.')


def parse_product_rows(rows: list[dict], default_category: str | None = None) -> tuple[list[dict],list[str]]:
    """사용자가 적법하게 확보한 자료만 받는다. 랭킹 1~40 고정."""
    result=[]; warnings=[]
    for index,row in enumerate(rows,1):
        rank=num(_lookup(row,'rank','순위','랭킹','ranking'))
        if not rank or rank<1 or rank>MAX_RANK:continue
        code=_lookup(row,'category_code','카테고리코드','카테고리ID') or default_category or ''
        title=_lookup(row,'title','상품명','product_name','name')
        if not title or not code:
            warnings.append(f'{index}행: 카테고리코드 또는 상품명 누락');continue
        result.append({'category_code':code,'rank':rank,
            'product_id':_lookup(row,'product_id','productId','상품ID','상품번호'),
            'title':title,'price':num(_lookup(row,'price','판매가','가격')),
            'reviews':num(_lookup(row,'reviews','리뷰수','리뷰','review_count')),
            'brand':_lookup(row,'brand','브랜드'), 'delivery':_lookup(row,'delivery','배송방식','배송'),
            'url':_lookup(row,'url','상품URL','링크')})
    return result,warnings


def product_group(p: dict) -> str:
    if p.get('product_id'):return 'id:'+str(p['product_id'])
    s=compact(p.get('title'))
    # 색상·수량 옵션에 관한 최소한의 정리만 한다. 서로 다른 상품을 과도하게 병합하지 않는다.
    for suffix in ('블랙','화이트','그레이','베이지','브라운','핑크','블루','레드','내추럴','2개입','3개입','1개입'):
        s=s.replace(suffix,'')
    return 'title:'+s[:100]


def extract_keyword(title: str, aliases: dict[str,list[str]] | None = None) -> str:
    aliases=aliases or KEYWORD_ALIASES
    target=compact(title)
    matched=[]
    for main,synonyms in aliases.items():
        for candidate in [main,*synonyms]:
            if compact(candidate) in target:
                matched.append((len(compact(candidate)),main))
    if matched:return sorted(matched,reverse=True)[0][1]
    return '' # 근거 없는 일반 단어 조합을 메인키워드로 만들지 않는다.


def import_products(conn, rows: list[dict]) -> dict:
    catmap={r['code']:dict(r) for r in conn.execute('SELECT * FROM categories')}
    accepted=[]; skipped=[]; seen=set()
    snapshot=utcnow()
    for x in rows:
        code=x['category_code']; cat=catmap.get(code)
        if cat is None:skipped.append(f'{code}: 등록되지 않은 카테고리');continue
        if not cat['is_leaf']:skipped.append(f'{code}: 최하위 아님');continue
        if cat['fit']!='적합':skipped.append(f'{code}: {cat["fit"]} 카테고리');continue
        k=(code,x['rank'])
        if k in seen:skipped.append(f'{code} {x["rank"]}위 중복');continue
        seen.add(k);accepted.append(x)
    for x in accepted:
        conn.execute('''INSERT INTO products(category_code,rank,product_id,title,price,reviews,brand,delivery,url,snapshot_at)
        VALUES (?,?,?,?,?,?,?,?,?,?)''',
        (x['category_code'],x['rank'],x['product_id'],x['title'],x['price'],x['reviews'],x['brand'],x['delivery'],x['url'],snapshot))
    for code in {x['category_code'] for x in accepted}:
        n=sum(1 for x in accepted if x['category_code']==code)
        conn.execute('''INSERT INTO scans(category_code,state,row_count,message,updated_at) VALUES (?,?,?,?,?)
        ON CONFLICT(category_code) DO UPDATE SET state=excluded.state,row_count=excluded.row_count,
        message=excluded.message, updated_at=excluded.updated_at''',(code,'완료' if n==40 else '부분 수집',n,'자료 파일을 통한 수집',snapshot))
    conn.commit()
    refresh_keywords(conn,{x['category_code'] for x in accepted})
    event(conn,'랭킹 상품 가져오기',f'저장 {len(accepted)}행, 제외 {len(skipped)}행')
    return {'imported':len(accepted),'skipped':len(skipped),'messages':skipped[:15]}


def latest_products(conn, code: str) -> list[dict]:
    last=conn.execute('SELECT MAX(snapshot_at) FROM products WHERE category_code=?',(code,)).fetchone()[0]
    if not last:return []
    return [dict(x) for x in conn.execute('SELECT * FROM products WHERE category_code=? AND snapshot_at=? ORDER BY rank',(code,last))]


def refresh_keywords(conn, categories: set[str]):
    for code in categories:
        p=latest_products(conn,code)
        grouped=defaultdict(list)
        seen=set()
        for row in p:
            key=product_group(row)
            if key in seen: continue
            seen.add(key)
            kw=extract_keyword(row['title'])
            if kw: grouped[kw].append(row['title'])
        old={x['keyword']:x['status'] for x in conn.execute('SELECT keyword,status FROM keywords WHERE category_code=?',(code,))}
        conn.execute('DELETE FROM keywords WHERE category_code=?',(code,))
        for kw, titles in grouped.items():
            conn.execute('''INSERT INTO keywords(category_code,keyword,product_count,sample_titles,status,updated_at)
            VALUES (?,?,?,?,?,?)''',(code,kw,len(titles),' | '.join(titles[:3]),old.get(kw,'검증 대기'),utcnow()))
    conn.commit()


def evaluate(conn, code: str) -> dict:
    cat=conn.execute('SELECT * FROM categories WHERE code=?',(code,)).fetchone()
    if cat is None:return {'score':None,'reason':'카테고리 없음'}
    if cat['fit']!='적합':return {'score':None,'reason':f'1차 필터: {cat["fit"]}'}
    allp=latest_products(conn,code)
    prices=[x['price'] for x in allp if x['price'] is not None]
    reviews=[x['reviews'] for x in allp if x['reviews'] is not None]
    if len(allp)<10 or len(prices)<10 or len(reviews)<10:
        return {'score':None,'reason':f'자료 부족: 상품 {len(allp)}개, 가격 {len(prices)}개, 리뷰 {len(reviews)}개',
                'total':len(allp),'prices':len(prices),'reviews':len(reviews)}
    unique={product_group(p):p for p in allp}
    unique_products=list(unique.values())
    price_ratio=sum(PRICE_MIN<=p<=PRICE_MAX for p in prices)/len(prices)
    lowrev_ratio=sum(r<=500 for r in reviews)/len(reviews)
    kws={extract_keyword(p['title']) for p in unique_products}- {''}
    brand_values=[compact(p['brand']) for p in allp if p['brand']]
    unique_brands=len(set(brand_values))
    brand_score=5 if not brand_values else round(10*(1-max(Counter(brand_values).values())/len(brand_values)))
    has_risk=any(t in cat['category_name'] for t in MIXED_HINTS)
    safe_score=6 if has_risk else 10
    parts={'price':round(30*price_ratio,1),'review':round(25*lowrev_ratio,1),
           'keyword':min(25,5*len(kws)),'brand':brand_score,'handling':safe_score}
    score=round(sum(parts.values()),1)
    return {'score':score,'parts':parts,'reason':'우선 탐색' if score>=75 else '추가 검토' if score>=55 else '후순위',
            'total':len(allp),'unique':len(unique_products),'price_ratio':price_ratio,
            'lowrev_ratio':lowrev_ratio,'keyword_count':len(kws),'median_price':int(median(prices)),
            'keywords':sorted(kws),'sources':'허용된 입력 자료; 실제 매출 추정 아님'}


def dashboard_rows(conn) -> list[dict]:
    rs=[]
    for r in conn.execute('SELECT * FROM categories WHERE is_leaf=1 ORDER BY path'):
        item=dict(r); analysis=evaluate(conn,r['code'])
        item.update({f'analysis_{k}':v for k,v in analysis.items() if k!='parts'})
        rs.append(item)
    return rs


def import_bulsaja_json(conn, payload: Any) -> dict:
    """과거에 사용한 불사자 수집 JSON의 summary.fields만 수입. 랭킹과 매출 중복은 검증 안 됨."""
    records=payload.get('records') if isinstance(payload,dict) else payload
    if not isinstance(records,list):raise ValueError('records 배열을 찾을 수 없습니다.')
    n=0; errors=[]
    for item in records:
        keyword=normalize(item.get('keyword'))
        fields=item.get('summary',{}).get('fields',{})
        def field(k):return (fields.get(k) or {}).get('value')
        revenue=num(field('totalRevenue'))
        if not keyword or revenue is None:
            errors.append(keyword or '(키워드 없음)');continue
        measured=normalize(item.get('capturedAt')) or utcnow()
        searches=num(field('naverMonthlySearch'))
        reviews=num(field('top10AverageReviews'))
        share=(item.get('summary',{}).get('deliveryShares') or {}).get('판매자로켓')
        conn.execute('''INSERT OR REPLACE INTO markets(keyword,measured_at,first_page_revenue,monthly_search,top10_reviews,seller_rocket_pct,note,source)
        VALUES (?,?,?,?,?,?,?,?)''',(keyword,measured,revenue,searches,reviews,share,
           '1페이지 추정. 상품 옵션·상품군 중복을 제거한 매출이 아님.','사용자가 제공한 불사자 JSON'))
        n+=1
    conn.commit()
    event(conn,'1페이지 데이터 수입',f'시장측정 {n}건')
    return {'imported':n,'failed':errors}


def exported_keywords(conn) -> list[dict]:
    records=[]
    for x in conn.execute('''SELECT k.keyword,c.path,k.product_count,k.status,k.updated_at
                FROM keywords k JOIN categories c ON k.category_code=c.code
                ORDER BY k.status,k.product_count DESC'''):
        r=dict(x)
        market=conn.execute('SELECT * FROM markets WHERE keyword=? ORDER BY measured_at DESC LIMIT 1',(r['keyword'],)).fetchone()
        if market:
            r.update({'market_revenue':market['first_page_revenue'],'monthly_search':market['monthly_search'],
                      'top10_reviews':market['top10_reviews'],'measured_at':market['measured_at']})
        records.append(r)
    return records


def database_backup(conn: sqlite3.Connection) -> bytes:
    """WAL 모드에서도 변경사항을 포함한 일관된 SQLite 백업."""
    import tempfile
    with tempfile.TemporaryDirectory() as dirname:
        path=Path(dirname) / 'sourcing_backup.db'
        dest=sqlite3.connect(path)
        try:
            conn.backup(dest)
        finally:
            dest.close()
        return path.read_bytes()


def dicts_to_csv(rows: list[dict]) -> bytes:
    if not rows:return '\ufeff'.encode('utf-8')
    out=io.StringIO();fieldnames=list(dict.fromkeys(key for r in rows for key in r.keys()))
    writer=csv.DictWriter(out,fieldnames=fieldnames,extrasaction='ignore');writer.writeheader();writer.writerows(rows)
    return ('\ufeff'+out.getvalue()).encode('utf-8')
