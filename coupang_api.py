"""쿠팡 공식 읽기 전용 카테고리 API.

Access/Secret 키는 요청 생성 중에만 사용하며 파일/로그/DB에 기록하지 않는다.
IP 접근 제한 또는 보호 장치 차단은 네트워크 측에서 해결해야 하며 우회하지 않는다.
"""
from __future__ import annotations
import gzip
import hashlib
import hmac
import json
import re
import urllib.error
import urllib.request
import zlib
from datetime import datetime, timezone

HOST = 'https://api-gateway.coupang.com'
PATH = '/v2/providers/seller_api/apis/api/v1/marketplace/meta/display-categories'
QUERY = 'registrationType=RFM&locale=kr'


class CoupangAPIError(RuntimeError):
    def __init__(self, status: int, reason: str, message: str):
        self.status = status
        self.reason = reason
        super().__init__(message)


def make_signature(access_key: str, secret_key: str, signed_date: str,
                   path: str = PATH, query: str = QUERY) -> str:
    # 쿠팡 공식 규칙: signed-date + METHOD + path + raw-query (물음표 제외)
    message = signed_date + 'GET' + path + query
    sig = hmac.new(secret_key.encode('utf-8'), message.encode('utf-8'), hashlib.sha256).hexdigest()
    return f'CEA algorithm=HmacSHA256, access-key={access_key}, signed-date={signed_date}, signature={sig}'


def readable_response(raw: bytes, content_encoding: str = '') -> str:
    """HTTP 오류 본문을 안전하게 표시. 압축 바이너리를 문자로 잘못 출력하지 않는다."""
    if not raw:
        return ''
    try:
        ce = (content_encoding or '').lower()
        if 'gzip' in ce or raw.startswith(b'\x1f\x8b'):
            raw = gzip.decompress(raw)
        elif 'deflate' in ce:
            try:
                raw = zlib.decompress(raw)
            except zlib.error:
                raw = zlib.decompress(raw, -zlib.MAX_WBITS)
        elif 'br' in ce:
            try:
                import brotli
                raw = brotli.decompress(raw)
            except (ImportError, Exception):  # noqa: B014 - graceful fallback only
                return ''
    except (OSError, ValueError, EOFError, zlib.error):
        return ''
    text = raw[:4096].decode('utf-8', 'replace')
    # 인식 불가능한 바이너리, 과도한 제어문자·바이너리 교체문자 출력 방지
    if text.count('\ufffd') > 2 or sum(1 for c in text if ord(c) < 32 and c not in '\n\t\r') > 1:
        return ''
    text = re.sub(r'<[^>]*>', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:400]


def classify_error(status: int, body: str) -> CoupangAPIError:
    lower = body.lower()
    if status == 403:
        if 'not allowed ip' in lower or 'forbidden ip' in lower:
            reason = 'IP_NOT_ALLOWED'
            msg = ('HTTP 403 — 쿠팡에 등록된 API 호출 허용 공인 IP와 현재 PC의 공인 IP가 다를 수 있습니다. '
                   'WING의 API 키 연동 방식(자체개발 여부)과 IP 설정을 확인하세요. 설정 변경 후 최대 30분 기다리세요.')
        elif 'access denied' in lower or not body:
            reason = 'ACCESS_BLOCKED'
            msg = ('HTTP 403 — 쿠팡 보안 시스템의 접근 제한 또는 API 키의 연동업체/IP 설정 문제일 수 있습니다. '
                   '버튼 반복 클릭을 중단하고 10분 뒤 WING 연동 설정을 확인하세요.')
        else:
            reason = 'FORBIDDEN'
            msg = ('HTTP 403 — 요청이 거부됐습니다. API 연동업체, 자체개발 등록 공인 IP 및 계정 권한을 확인하세요.')
    elif status == 401:
        reason = 'AUTHENTICATION'
        msg = ('HTTP 401 — Access/Secret Key, PC 시각(자동 동기화), HMAC 서명 등 인증 정보를 확인하세요.')
    else:
        reason = 'HTTP_ERROR'
        msg = f'쿠팡 공식 API 요청 실패: HTTP {status}.'
    if body and len(body) < 180 and not any(key in lower for key in ('<script', 'access-key=', 'signature=')):
        msg += f' (응답: {body})'
    return CoupangAPIError(status, reason, msg)


def fetch_rfm_categories(access_key: str, secret_key: str, timeout: int = 30) -> dict:
    """쿠팡 공식 RFM 카테고리 API 조회. 차단 시 자동 재시도하지 않는다."""
    access_key, secret_key = (access_key or '').strip(), (secret_key or '').strip()
    if not access_key or not secret_key:
        raise ValueError('Access Key와 Secret Key가 필요합니다.')
    signed_date = datetime.now(timezone.utc).strftime('%y%m%dT%H%M%SZ')
    req = urllib.request.Request(
        HOST + PATH + '?' + QUERY,
        headers={
            'Authorization': make_signature(access_key, secret_key, signed_date),
            'Content-Type': 'application/json;charset=UTF-8',
            'Accept': 'application/json',
            'Accept-Encoding': 'identity',
        },
        method='GET',
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        encoding = exc.headers.get('Content-Encoding', '') if exc.headers else ''
        details = readable_response(exc.read(8192), encoding)
        raise classify_error(exc.code, details) from None
    except urllib.error.URLError as exc:
        raise RuntimeError(f'쿠팡 서버 연결 실패. 인터넷 연결 상태와 네트워크 설정을 확인하세요. ({type(exc.reason).__name__})') from None
    if str(result.get('code', 'SUCCESS')).upper() not in ('SUCCESS', '200'):
        raise RuntimeError('쿠팡 API 오류: ' + str(result.get('message') or result.get('code'))[:250])
    return result
