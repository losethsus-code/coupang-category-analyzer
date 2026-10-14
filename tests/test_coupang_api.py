import gzip
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from coupang_api import make_signature, readable_response, classify_error, fetch_rfm_categories, CoupangAPIError, PATH, QUERY

class CoupangAPITests(unittest.TestCase):
    def test_signature_matches_reference(self):
        import hashlib, hmac
        date='261013T091500Z'
        expected=hmac.new(b'secret', (date+'GET'+PATH+QUERY).encode(),hashlib.sha256).hexdigest()
        self.assertIn('signature='+expected,make_signature('access','secret',date))
    def test_compressed_error_decoding(self):
        body='403 [FORBIDDEN] Not allowed IP'.encode()
        self.assertEqual(readable_response(gzip.compress(body),'gzip'),body.decode())
    def test_unreadable_error_hidden(self):
        self.assertEqual(readable_response(b'\x00\x01\x02\x03\x04\xff\xff'),'')
    def test_classification(self):
        err=classify_error(403,'403 [FORBIDDEN] Not allowed IP')
        self.assertEqual(err.reason,'IP_NOT_ALLOWED')
        self.assertIn('공인 IP',str(err))
        self.assertEqual(classify_error(401,'').reason,'AUTHENTICATION')
    def test_no_key_leak_with_403(self):
        body=gzip.compress(b'Sorry! Access denied')
        http_err=HTTPError('https://unused',403,'Forbidden',{'Content-Encoding':'gzip'},io.BytesIO(body))
        with patch('coupang_api.urllib.request.urlopen',side_effect=http_err) as urlopen:
            with self.assertRaises(CoupangAPIError) as caught:
                fetch_rfm_categories('my-access-key','my-secret-key')
        self.assertEqual(caught.exception.reason,'ACCESS_BLOCKED')
        self.assertNotIn('my-secret-key',str(caught.exception))
        self.assertEqual(urlopen.call_count,1)
    def test_keys_not_sent_if_blank(self):
        with self.assertRaises(ValueError): fetch_rfm_categories('','')

if __name__=='__main__': unittest.main()
