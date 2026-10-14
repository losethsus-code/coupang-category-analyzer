from datetime import datetime, timedelta
import pytest
from core import connection
from one_product import start, current, advance, update_notes, latest_history, deadline_display, market_snapshot


def test_only_one_candidate_and_close(tmp_path):
    conn=connection(tmp_path/'test.db')
    candidate=start(conn,' 화장품정리함 ','꺼내기 불편','분리 칸막이')
    assert candidate['keyword']=='화장품정리함'
    with pytest.raises(ValueError):
        start(conn,'신발정리대')
    advance(conn,candidate['id'],'보류')
    assert current(conn) is None
    assert start(conn,'신발정리대')['keyword']=='신발정리대'


def test_sample_requires_verified_risks(tmp_path):
    conn=connection(tmp_path/'test.db')
    x=start(conn,'신발정리대')
    with pytest.raises(ValueError):
        advance(conn,x['id'],'샘플주문')
    x=update_notes(conn,x['id'],problem='불편',difference='폭 조절',market_note='있음',
        manufacturer_note='소량 문의',checks_cert=True,checks_cost=True,checks_shipping=True)
    advance(conn,x['id'],'샘플주문')
    assert current(conn) is None
    assert latest_history(conn)[0]['state']=='샘플주문'


def test_existing_market_and_deadline(tmp_path):
    conn=connection(tmp_path/'test.db')
    x=start(conn,'화장품정리함')
    assert datetime.fromisoformat(x['deadline_at'])-datetime.fromisoformat(x['created_at'])==timedelta(hours=72)
    assert deadline_display(x,datetime.fromisoformat(x['deadline_at'])+timedelta(seconds=1))[1]
    conn.execute('INSERT INTO markets(keyword,measured_at,first_page_revenue) VALUES (?,?,?)',
        ('화장품정리함',x['created_at'],317000000))
    conn.commit()
    assert market_snapshot(conn,'화장품정리함')['first_page_revenue']==317000000
