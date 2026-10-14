import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import (category_fit, flatten_tree, parse_category_rows, save_categories, connection,
                  set_category_fit, parse_product_rows, parse_csv_bytes, import_products,
                  evaluate, latest_products, exported_keywords, import_bulsaja_json)

class ExplorerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.db=connection(Path(self.temp.name)/'sourcing.db')
        root=Path(__file__).resolve().parents[1]
        self.categories=json.loads((root/'sample_data/categories_example.json').read_text(encoding='utf-8'))
    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def test_nested_category_and_leaf(self):
        rows=flatten_tree(self.categories)
        self.assertGreaterEqual(len(rows),5)
        m={r['code']:r for r in rows}
        self.assertEqual(m['999006']['depth'],4)
        self.assertTrue(m['999006']['is_leaf'])
        self.assertFalse(m['999001']['is_leaf'])
        self.assertEqual(m['999004']['fit'],'제외')
        self.assertEqual(m['999003']['fit'],'조건부')
        self.assertEqual(m['999002']['fit'],'적합')
        self.assertFalse(any('패션' in r['path'] for r in rows))

    def test_fit_exclusion_conservative(self):
        self.assertEqual(category_fit('생활용품 > 수납/정리 > 침대')[0],'제외')
        self.assertEqual(category_fit('생활용품 > 수납/정리 > 선반/진열대')[0],'조건부')
        self.assertEqual(category_fit('생활용품 > 수납/정리 > 화장품 정리함')[0],'적합')
        self.assertEqual(category_fit('생활용품 > 수납/정리 > 신제품')[0],'조건부')

    def test_override_survives_reimport(self):
        rows=flatten_tree(self.categories)
        save_categories(self.db,rows)
        set_category_fit(self.db,'999003','적합','소형 모델만 수집')
        save_categories(self.db,rows)
        r=self.db.execute('SELECT fit,reason FROM categories WHERE code=?',('999003',)).fetchone()
        self.assertEqual(r['fit'],'적합')
        self.assertEqual(r['reason'],'소형 모델만 수집')

    def test_csv_category_mapping(self):
        data=Path(__file__).resolve().parents[1]/'sample_data/categories_example.csv'
        r=parse_category_rows(parse_csv_bytes(data.read_bytes()))
        self.assertEqual(len(r),4)
        self.assertEqual(next(x for x in r if x['code']=='999006')['depth'],4)

    def test_product_import_and_scoring(self):
        save_categories(self.db,flatten_tree(self.categories))
        csv_path=Path(__file__).resolve().parents[1]/'sample_data/products_example.csv'
        parsed,warnings=parse_product_rows(parse_csv_bytes(csv_path.read_bytes()))
        self.assertEqual(len(parsed),40)
        self.assertFalse(warnings)
        result=import_products(self.db,parsed)
        self.assertEqual(result['imported'],40)
        self.assertEqual(len(latest_products(self.db,'999002')),40)
        score=evaluate(self.db,'999002')
        self.assertIsNotNone(score['score'])
        self.assertIn('화장품정리함',score['keywords'])
        self.assertTrue(any(x['keyword']=='화장품정리함' for x in exported_keywords(self.db)))
        second=import_products(self.db,parsed)
        self.assertEqual(second['imported'],40)
        self.assertEqual(len(latest_products(self.db,'999002')),40)

    def test_excluded_category_skips_product(self):
        save_categories(self.db,flatten_tree(self.categories))
        products=[{'category_code':'999004','rank':1,'product_id':'1','title':'대형 수납장','price':28000,'reviews':3,
                   'brand':'','delivery':'','url':''}]
        self.assertEqual(import_products(self.db,products)['imported'],0)
        self.assertEqual(evaluate(self.db,'999004')['score'],None)

    def test_bulsaja_import(self):
        value={'records':[{'keyword':'화장품정리함','capturedAt':'2026-10-12T13:10:30Z',
              'summary':{'fields':{'totalRevenue':{'value':317490760},'naverMonthlySearch':{'value':7640},
              'top10AverageReviews':{'value':698}},'deliveryShares':{'판매자로켓':65}}}]}
        r=import_bulsaja_json(self.db,value)
        self.assertEqual(r['imported'],1)
        entry=self.db.execute('SELECT * FROM markets').fetchone()
        self.assertEqual(entry['first_page_revenue'],317490760)
        self.assertEqual(entry['monthly_search'],7640)
        self.assertEqual(entry['seller_rocket_pct'],65)

if __name__=='__main__': unittest.main()
