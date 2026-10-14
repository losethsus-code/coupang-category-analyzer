import json, sqlite3, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import (connection,flatten_tree,save_categories,parse_csv_bytes,parse_product_rows,
                  import_products,exported_keywords,import_bulsaja_json,database_backup)
from search_1p import (setup,queue_keywords,queue_rows,parse_search_rows,save_search_rows,evaluate_keyword,latest_snapshot)

ROOT=Path(__file__).resolve().parents[1]
class EndToEndTests(unittest.TestCase):
    def test_full_offline_sequence_and_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn=connection(Path(tmp)/'sourcing.db');setup(conn)
            categories=json.loads((ROOT/'sample_data/categories_example.json').read_text())
            save_categories(conn,flatten_tree(categories))
            prod,_=parse_product_rows(parse_csv_bytes((ROOT/'sample_data/products_example.csv').read_bytes()))
            self.assertEqual(import_products(conn,prod)['imported'],40)
            words=exported_keywords(conn)
            self.assertTrue(words)
            queue_keywords(conn,[r['keyword'] for r in words]);self.assertTrue(queue_rows(conn))
            search,_=parse_search_rows(parse_csv_bytes((ROOT/'sample_data/search_1p_example.csv').read_bytes()))
            saved=save_search_rows(conn,search)
            self.assertEqual(len(saved['snapshots']),2)
            saved_again=save_search_rows(conn,search)
            self.assertEqual(len(saved_again['snapshots']),0)
            self.assertEqual(set(saved_again['unchanged']),{'신발정리대','화장품정리함'})
            self.assertEqual(evaluate_keyword(conn,'화장품정리함')['market_state'],'미측정')
            summary={'records':[{'keyword':'화장품정리함','capturedAt':'2026-10-12T13:10:30Z',
              'summary':{'fields':{'totalRevenue':{'value':317490760},'naverMonthlySearch':{'value':7640},
              'top10AverageReviews':{'value':698}},'deliveryShares':{'판매자로켓':65}}}]}
            self.assertEqual(import_bulsaja_json(conn,summary)['imported'],1)
            self.assertEqual(evaluate_keyword(conn,'화장품정리함')['market_revenue'],317490760)
            db_bytes=database_backup(conn)
            savedfile=Path(tmp)/'restored.db';savedfile.write_bytes(db_bytes)
            recovered=sqlite3.connect(savedfile)
            try:
                self.assertGreater(recovered.execute('SELECT COUNT(*) FROM search_products').fetchone()[0],0)
                self.assertGreater(recovered.execute('SELECT COUNT(*) FROM categories').fetchone()[0],0)
                self.assertEqual(recovered.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            finally:recovered.close();conn.close()
if __name__=='__main__':unittest.main()
