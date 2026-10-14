import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import connection, import_bulsaja_json
from search_1p import (setup,search_url,parse_search_rows,parse_bulsaja_products,
                       save_search_rows,latest_search_products,latest_snapshot,evaluate_keyword,
                       queue_keywords,queue_rows,set_job_state)

class Search1PTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.conn=connection(Path(self.tmp.name)/'db.sqlite')
        setup(self.conn)
    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_url_encoding(self):
        url=search_url('화장품 정리함')
        self.assertEqual(url,'https://www.coupang.com/np/search?q=%ED%99%94%EC%9E%A5%ED%92%88%20%EC%A0%95%EB%A6%AC%ED%95%A8')
        with self.assertRaises(ValueError):search_url('')

    def test_queue_reimport_and_state(self):
        self.assertEqual(queue_keywords(self.conn,['신발정리대','화장품정리함','화장품정리함']),2)
        self.assertEqual(queue_keywords(self.conn,['신발정리대']),0)
        set_job_state(self.conn,'화장품정리함','심층검증','저리뷰 확인')
        queue_keywords(self.conn,['화장품정리함'])
        row=next(x for x in queue_rows(self.conn) if x['keyword']=='화장품정리함')
        self.assertEqual(row['state'],'심층검증')
        self.assertEqual(row['memo'],'저리뷰 확인')

    def test_parse_and_snapshot_no_fake_sales(self):
        source=[{'keyword':'화장품정리함','rank':1,'title':'투명 화장품 정리함','price':'19,900원','reviews':'170개'},
                {'keyword':'화장품정리함','rank':2,'title':'회전식 화장품 정리함','price':'27,900원','reviews':'200개'}]
        rows,errors=parse_search_rows(source)
        self.assertFalse(errors)
        saved=save_search_rows(self.conn,rows)
        self.assertEqual(saved['snapshots'][0]['count'],2)
        self.assertEqual(latest_snapshot(self.conn,'화장품정리함')['completeness'],'일부 순위 표본')
        self.assertEqual(len(latest_search_products(self.conn,'화장품정리함')),2)
        result=evaluate_keyword(self.conn,'화장품정리함')
        self.assertIsNone(result['market_revenue'])
        self.assertEqual(result['market_state'],'미측정')
        self.assertEqual(result['status'],'추가 검증 필요')

    def test_bulsaja_grids_convert(self):
        original={'records':[{'keyword':'신발정리대','capturedAt':'2026-10-12T06:00:00Z',
            'summary':{'fields':{'totalRevenue':{'value':483812570},'naverMonthlySearch':{'value':5730},
            'top10AverageReviews':{'value':1449}},'deliveryShares':{'판매자로켓':52}},
            'agGrids':[{'rows':[{'cells':{'rank':{'text':'5'},'title':{'text':'자석 신발 정리대 블랙'},
            'price':{'text':'19,900원'},'review':{'text':'225개'},
            'wingStat.salesLast28d':{'text':'3,182개'},
            'wingStat.monthlyRevenue':{'text':'63,321,800원'}}}]}]}]}
        rows,warnings=parse_bulsaja_products(original)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['estimated_revenue'],63321800)
        import_bulsaja_json(self.conn,original)
        save_search_rows(self.conn,rows,source='불사자')
        ev=evaluate_keyword(self.conn,'신발정리대')
        self.assertEqual(ev['market_revenue'],483812570)
        self.assertEqual(ev['low_review_top20'],1)
        self.assertEqual(ev['mid_rank_sales_sum'],3182)
        self.assertFalse(ev['mid_rank_sales_is_deduped'])

    def test_two_keywords_and_duplicate_rank(self):
        rows,_=parse_search_rows([
            {'keyword':'신발정리대','rank':1,'title':'신발 정리대 1','price':10000},
            {'keyword':'신발정리대','rank':1,'title':'신발 정리대 2','price':10000},
            {'keyword':'북카트','rank':1,'title':'북카트 1','price':20000},
        ])
        outcome=save_search_rows(self.conn,rows)
        self.assertEqual(len(outcome['snapshots']),2)
        self.assertEqual(len(outcome['warnings']),1)
        self.assertEqual(len(queue_rows(self.conn)),2)

if __name__=='__main__':unittest.main()
