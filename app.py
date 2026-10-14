"""쿠팡 소싱 탐색기 MVP - Streamlit UI."""
from __future__ import annotations
import io
import json
import csv
import time
import streamlit as st
import pandas as pd
from one_product import setup as setup_one_product
from one_product_ui import render as render_one_product

from core import (
    connection, flatten_tree, parse_category_rows, save_categories, category_fit,
    set_category_fit, parse_csv_bytes, parse_product_rows, import_products,
    latest_products, evaluate, dashboard_rows, exported_keywords,
    import_bulsaja_json, dicts_to_csv, database_backup, KEYWORD_ALIASES, MAX_RANK, utcnow
)
from coupang_api import fetch_rfm_categories, CoupangAPIError
from search_1p import (setup as setup_search, search_url, queue_keywords, queue_rows, set_job_state,
    parse_search_rows, parse_bulsaja_products, save_search_rows, latest_search_products, evaluate_keyword)

st.set_page_config(page_title='쿠팡 소싱 탐색기',page_icon='📦',layout='wide',initial_sidebar_state='expanded')
st.markdown('''<style>
html,body,[class*="css"],p,div {font-family:"Malgun Gothic","Apple SD Gothic Neo",sans-serif;}
.block-container {padding-top:1.4rem; max-width:1480px;}
[data-testid="stSidebar"] {background:#101d2d;}
[data-testid="stSidebar"] * {color:#eef4fb !important;}
[data-testid="stMetric"] {background:#f4f7fb; padding:17px; border-radius:12px;border:1px solid #e3ebf4;}
[data-testid="stMetricValue"] {font-size:1.6rem;}
h1,h2,h3 {letter-spacing:-0.03em;}
.smallnote {color:#64748b;font-size:0.86rem;}
</style>''',unsafe_allow_html=True)

conn=connection()
setup_search(conn)
setup_one_product(conn)
with st.sidebar:
    st.markdown('## COUPANG  \\n SOURCING LAB')
    st.caption('로켓그로스 · 생활용품 중심')
    mode=st.radio('화면', ['이번 상품 1개', '기존 상세 도구'],label_visibility='collapsed')
    if mode == '기존 상세 도구':
        page=st.selectbox('기존 기능', ['대시보드','1. 카테고리 필터','2. 랭킹 40개 분석','3. 메인키워드 DB','4. 검색 1P 검증','설정·사용법'])
    else:
        page='이번 상품 1개'
    st.divider()
    st.caption('버전 0.6 · GitHub 통합 업데이트')
    st.caption('실행 주소: http://127.0.0.1:8789')
    st.caption('자료는 이 PC의 app_data/sourcing.db에 보관됩니다.')

cats=dashboard_rows(conn)
leaves=[x for x in cats]
active=[x for x in leaves if x['fit']=='적합']
reviewed=[x for x in leaves if x['analysis_score'] is not None]

if page=='이번 상품 1개':
    render_one_product(conn)

elif page=='대시보드':
    st.title('소싱 탐색 대시보드')
    st.caption('카테고리 필터 → 랭킹 40개 → 메인키워드 발굴 → 검색 1페이지 검증')
    cols=st.columns(4)
    for col,(label,val) in zip(cols,[('최하위 카테고리',len(leaves)),('1차 적합',len(active)),
        ('랭킹 분석 완료',len(reviewed)),('발굴 메인키워드',len(exported_keywords(conn)))]):
        col.metric(label, val)
    st.markdown('### 지금 할 일')
    if not leaves:
        st.info('① 카테고리 자료를 가져오세요. 공식 RFM API(본인 계정 키 필요) 또는 카테고리 Excel/JSON/CSV 파일을 사용할 수 있습니다.')
    elif not reviewed:
        st.info('② 적합 카테고리를 확인한 다음, 해당 카테고리의 랭킹 상품 자료(CSV)를 업로드하세요. 자료가 없는 카테고리는 미검증으로 유지합니다.')
    else:
        st.success('③ 점수가 높은 카테고리의 추출 메인키워드를 검토하고, 유망 키워드만 검색 1페이지에서 검증하세요.')
    st.markdown('### 카테고리 현황')
    if leaves:
        fit_counts=pd.DataFrame([{'판정':k,'개수':sum(x['fit']==k for x in leaves)} for k in ['적합','조건부','제외']])
        st.dataframe(fit_counts,hide_index=True,use_container_width=True)
        recommended=sorted([x for x in reviewed],key=lambda z:z['analysis_score'] or 0,reverse=True)
        if recommended:
            st.markdown('### 분석된 카테고리 순위')
            df=pd.DataFrame([{'카테고리':x['path'],'소싱점수':x['analysis_score'],
                '추천':x['analysis_reason'],'랭킹자료':x.get('analysis_total',0),
                '독립 키워드':x.get('analysis_keyword_count',0)} for x in recommended])
            st.dataframe(df,hide_index=True,use_container_width=True)
    st.caption('카테고리 점수는 상품 데이터에 기반한 탐색 우선순위이며, 매출이나 수익성의 증거가 아닙니다.')

elif page=='1. 카테고리 필터':
    st.title('1. 카테고리 선별')
    st.caption('생활용품 전체 하위 카테고리 → 최하위 구분 → 인증·대형·시즌 위험 카테고리 먼저 제외')
    tab1,tab2,tab3=st.tabs(['공식 RFM API', '파일 가져오기', '판정 검토·수정'])
    with tab1:
        st.info('쿠팡에서 발급받은 본인 계정의 API 키만 사용합니다. 비밀번호와 API 키는 DB에 저장하지 않습니다.')
        st.markdown('[쿠팡 로켓그로스 카테고리 API 공식 문서](https://developers.coupang.com/ko/api/rocket-growth/how-to-get-category-list-for-rocket-growth-products)')
        st.caption('403이 발생하면 WING의 API 키 연동 방식과 등록한 공인 IP를 확인하세요. 다른 셀러툴과 연결된 키의 설정을 함부로 변경하면 기존 서비스가 중단될 수 있습니다.')
        st.markdown('[쿠팡 공식 API 키 발급·연동 설정 가이드](https://developers.coupang.com/ko/getting-started/issue-open-api-keynew) · [현재 공인 IP 확인](https://www.findip.kr/)')
        pause_remaining=max(0,int(st.session_state.get('rfm_api_pause_until',0)-time.time()))
        if pause_remaining:
            st.warning(f'403 차단 후 보호 대기 중입니다. 약 {pause_remaining//60+1}분 후 다시 시도하세요. 그동안 「파일 가져오기」에서 공식 카테고리 Excel을 사용할 수 있습니다.')
        with st.form('api-credentials',clear_on_submit=False):
            access=st.text_input('Access Key',type='password')
            secret=st.text_input('Secret Key',type='password')
            submitted=st.form_submit_button('공식 API에서 로켓그로스 카테고리 1회 조회',type='primary',disabled=pause_remaining>0)
        if submitted:
            try:
                with st.spinner('공식 API 연결 중...'):
                    payload=fetch_rfm_categories(access,secret)
                    parsed=flatten_tree(payload,'생활용품')
                    if not parsed: raise ValueError('생활용품 카테고리를 찾지 못했습니다. 응답 구조를 확인해 주세요.')
                    count,skipped=save_categories(conn,parsed)
                st.success(f'생활용품 카테고리 {count}개 저장 / 서비스 비활성 {skipped}개 제외')
                st.rerun()
            except CoupangAPIError as exc:
                if exc.status == 403:
                    st.session_state['rfm_api_pause_until']=time.time()+600
                st.error(str(exc))
                st.info('점검 순서: ① WING의 연동업체/자체개발 선택 ② 자체개발 등록 공인 IP와 현재 IP 일치 ③ 설정을 바꾼 경우 30분 대기. API 없이 진행하려면 「파일 가져오기」 사용.')
            except Exception as exc:
                st.error(str(exc))
    with tab2:
        st.markdown('공식 카테고리 Excel, CSV 또는 **공식 API 응답 JSON** 파일을 넣어도 됩니다.')
        uploaded=st.file_uploader('카테고리 파일',type=['xlsx','csv','json'],key='cat-upload')
        if uploaded:
            try:
                data=uploaded.getvalue()
                if uploaded.name.lower().endswith('.json'):
                    parsed=flatten_tree(json.loads(data),'생활용품')
                elif uploaded.name.lower().endswith('.csv'):
                    parsed=parse_category_rows(parse_csv_bytes(data))
                else:
                    df=pd.read_excel(io.BytesIO(data),dtype=str).fillna('')
                    parsed=parse_category_rows(df.to_dict('records'))
                st.caption(f'인식된 생활용품 카테고리 {len(parsed)}개. 실제 최하위 판정: {sum(x["is_leaf"] for x in parsed)}개')
                if parsed:
                    st.dataframe(pd.DataFrame(parsed)[['code','path','depth','is_leaf','fit','reason']].head(50),hide_index=True,use_container_width=True)
                    if st.button('카테고리 DB에 반영',type='primary'):
                        count,skip=save_categories(conn,parsed)
                        st.success(f'{count}개 저장, {skip}개 제외')
                        st.rerun()
                else:st.warning('생활용품 계층을 찾지 못했습니다. 파일의 열 이름과 대카테고리 값을 확인하세요.')
            except Exception as exc: st.error(f'파일 읽기 실패: {exc}')
        st.caption('권장 CSV 열: category_code, 1차 카테고리, 2차 카테고리, 3차 카테고리, 4차 카테고리. 공식 파일은 헤더 구성에 따라 추가 매핑이 필요할 수 있습니다.')
        with open('sample_data/categories_example.csv','rb') as f:
            st.download_button('카테고리 예시 CSV 받기',f,'categories_example.csv','text/csv')
    with tab3:
        if not leaves: st.warning('카테고리를 먼저 가져오세요.')
        else:
            selection=st.selectbox('상태 필터', ['전체','적합','조건부','제외'])
            shown=[x for x in leaves if selection=='전체' or x['fit']==selection]
            st.dataframe(pd.DataFrame([{'code':x['code'],'경로':x['path'],'판정':x['fit'],
                '사유':x['reason'],'깊이':x['depth'],'구분':'실제 최하위' if x['is_leaf'] else '-'} for x in shown]),
                use_container_width=True,hide_index=True,height=370)
            if shown:
                selected=st.selectbox('수동 예외 처리할 카테고리', [x['code'] for x in shown], format_func=lambda c:next(x['path'] for x in shown if x['code']==c))
                current=next(x for x in shown if x['code']==selected)
                with st.form('manual-override'):
                    fit=st.selectbox('1차 필터 판정', ['적합','조건부','제외'],index=['적합','조건부','제외'].index(current['fit']))
                    reason=st.text_input('변경 이유',value=current['reason'])
                    save=st.form_submit_button('판정 저장')
                if save:
                    set_category_fit(conn,selected,fit,reason)
                    st.success('변경 기록 저장 완료')
                    st.rerun()
        st.caption('카테고리명 기반 위험 분류는 소싱 초기 필터일 뿐이며 제품별 인증 면제나 실제 포장 부피를 보증하지 않습니다.')

elif page=='2. 랭킹 40개 분석':
    st.title('2. 랭킹 상위 40개 분석')
    st.caption('1차 필터에서 적합 판정을 받은 최하위 카테고리만 분석. 키워드 발굴 전 단계입니다.')
    st.warning('이번 MVP는 쿠팡 상품페이지를 무단 자동 순회하지 않습니다. 사용자가 적법하게 확보한 순위·상품 자료 CSV를 입력받습니다.')
    if not active:
        st.info('먼저 1. 카테고리 필터에서 적합 판정인 최하위 카테고리를 등록하세요.')
    else:
        with st.expander('여러 카테고리 랭킹 자료 일괄 가져오기 (추천)', expanded=False):
            st.caption('파일에 category_code가 포함되면 여러 최하위 카테고리를 한 번에 처리합니다. 조건부·제외 카테고리는 자동 건너뜁니다.')
            bulk=st.file_uploader('복수 카테고리 CSV (category_code 열 필수)',type=['csv'],key='bulk-products')
            if bulk:
                try:
                    bulk_rows,bulk_warnings=parse_product_rows(parse_csv_bytes(bulk.getvalue()))
                    count_by_cat=pd.Series([x['category_code'] for x in bulk_rows]).value_counts() if bulk_rows else pd.Series(dtype=int)
                    st.write(f'{len(bulk_rows)}건 인식 / {len(count_by_cat)}개 카테고리')
                    if not count_by_cat.empty:
                        st.dataframe(count_by_cat.rename_axis('category_code').reset_index(name='입력 랭킹 수'),hide_index=True)
                    if st.button('적합 카테고리만 일괄 저장·평가',type='primary',disabled=not bulk_rows):
                        result=import_products(conn,bulk_rows)
                        st.success(f'{result["imported"]}건 저장 / {result["skipped"]}건 제외')
                        if result['messages']:st.caption('제외 원인 예: '+' / '.join(result['messages'][:3]))
                        st.rerun()
                except Exception as exc:st.error(f'일괄 가져오기 실패: {exc}')
        st.divider()
        cat=st.selectbox('분석할 카테고리', [x['code'] for x in active], format_func=lambda c:next(x['path'] for x in active if x['code']==c))
        current=next(x for x in active if x['code']==cat)
        st.caption(f'선택된 카테고리 코드: {cat} / 단계: {current["depth"]}차')
        uploaded=st.file_uploader('해당 카테고리의 랭킹 상품 CSV 업로드',type=['csv'],key='product-upload')
        if uploaded:
            try:
                parsed,warnings=parse_product_rows(parse_csv_bytes(uploaded.getvalue()),default_category=cat)
                parsed=[x for x in parsed if x['category_code']==cat]
                st.write(f'사용 가능한 1~40위 자료: {len(parsed)}개')
                if parsed:st.dataframe(pd.DataFrame(parsed).head(40),hide_index=True,use_container_width=True)
                if warnings:st.warning('누락: '+' / '.join(warnings[:5]))
                if st.button('상품 40위 데이터 저장 및 점수 계산',type='primary',disabled=not parsed):
                    result=import_products(conn,parsed)
                    st.success(f'등록 {result["imported"]}건. 누락/제외 {result["skipped"]}건')
                    st.rerun()
            except Exception as exc:st.error(str(exc))
        st.caption('한 카테고리 40개 초과 자료를 넣어도 랭킹 1~40위만 사용합니다. 10개 미만이면 점수를 계산하지 않습니다.')
        with open('sample_data/products_example.csv','rb') as f:
            st.download_button('랭킹 상품 CSV 예시 받기',f,'products_example.csv','text/csv')
        result=evaluate(conn,cat)
        st.markdown('### 소싱 적합도')
        if result['score'] is None:st.info(result['reason'])
        else:
            a,b,c=st.columns(3)
            a.metric('소싱 점수',f'{result["score"]}/100')
            b.metric('대표가격(중앙값)',f'{result["median_price"]:,}원')
            c.metric('독립 상품군',result['unique'])
            st.write(f'판정: **{result["reason"]}** / 1.5만~3만원 비율 {result["price_ratio"]:.1%} / 저리뷰 비율 {result["lowrev_ratio"]:.1%}')
            st.json(result['parts'])
            st.write('추출 키워드:', ', '.join(result['keywords']) if result['keywords'] else '사전에 일치하는 키워드 없음 — 사용자 보완 필요')
        products=latest_products(conn,cat)
        if products:
            st.markdown('### 최신 상품 1~40위')
            st.dataframe(pd.DataFrame(products)[['rank','title','price','reviews','brand','delivery','product_id']],
                use_container_width=True,hide_index=True)

elif page=='3. 메인키워드 DB':
    st.title('3. 메인키워드 DB')
    st.caption('유사어를 대표 메인키워드로 통합합니다. 발굴된 키워드는 1페이지 시장 검증 전까지 판단 보류입니다.')
    words=exported_keywords(conn)
    if words:
        st.dataframe(pd.DataFrame(words),use_container_width=True,hide_index=True)
        st.download_button('키워드 DB CSV 다운로드',dicts_to_csv(words),'keyword_candidates.csv','text/csv',type='primary')
    else:st.info('랭킹 상품을 가져오면 메인키워드 후보가 이곳에 표시됩니다.')
    with st.expander('현재 적용된 유사어 통합 사전'):
        st.json(KEYWORD_ALIASES)
        st.caption('초기에는 검증된 사전과 상품명에 일치하는 키워드만 추출합니다. 미등록 상품군을 억지로 만들어 내지 않습니다.')

elif page=='4. 검색 1P 검증':
    st.title('4. 쿠팡 검색 1페이지 검증')
    st.caption('카테고리에서 발굴한 메인키워드를 관리하고, 적법하게 확보한 검색 1P 자료로 시장 적합도를 비교합니다.')
    st.warning('이 프로그램이 쿠팡 검색 페이지를 자동으로 요청하는 기능은 아직 없습니다. 직접 URL 접속은 접근 거부(403)로 확인되지 않았습니다. 우회하지 않습니다.')

    with st.expander('A. 메인키워드 검증 대기열 · 검색 링크', expanded=True):
        st.markdown('**키워드 발굴 → 대기열에 넣기 → 검색 1페이지 분석** 순서입니다. 같은 키워드를 다시 등록해도 중복 생성되지 않습니다.')
        words=exported_keywords(conn)
        if words and st.button(f'카테고리에서 발굴한 {len(set(x["keyword"] for x in words))}개 키워드 대기열에 등록'):
            n=queue_keywords(conn,[x['keyword'] for x in words])
            st.success(f'신규 {n}개 등록 / 이미 등록된 항목은 그대로 유지')
            st.rerun()
        with st.form('manual-keywords'):
            txt=st.text_area('직접 키워드 추가 (쉼표 또는 줄바꿈)',placeholder='화장품정리함, 신발정리대, 슬리퍼거치대',height=85)
            submitted=st.form_submit_button('키워드 추가')
        if submitted:
            items=[x.strip() for x in txt.replace('\n',',').split(',') if x.strip()]
            added=queue_keywords(conn,items)
            st.success(f'신규 {added}개 등록 / 기존 중복 제외')
            st.rerun()
        jobs=queue_rows(conn)
        if jobs:
            st.dataframe(pd.DataFrame([{
                '키워드':x['keyword'],'상태':x['state'],'검증 1P 상품행':x['product_rows'],
                '불사자 1P 추정매출':x.get('market_revenue'),'월 검색량':x.get('monthly_search'),
                '쿠팡 검색주소':x['search_url']
            } for x in jobs]),use_container_width=True,hide_index=True,column_config={
                '쿠팡 검색주소':st.column_config.LinkColumn('쿠팡 검색 열기',display_text='검색 페이지 열기')})
            chosen=st.selectbox('키워드별 상세 확인', [x['keyword'] for x in jobs],key='chosen-search')
            st.link_button('쿠팡에서 이 키워드 검색 열기',search_url(chosen))
            with st.form('job-state'):
                state=st.selectbox('분석 진행 상태', ['검증 대기','검증 진행','1차 통과','심층검증','보류','탈락','완료'])
                note=st.text_input('메모',placeholder='예: 1688 소형 차별화 상품 먼저 확인')
                update=st.form_submit_button('상태 저장')
            if update:
                set_job_state(conn,chosen,state,note)
                st.success('키워드 상태가 저장됐습니다.')
                st.rerun()
        else:
            st.info('우선 키워드를 추가하면 여러 검색어의 검증 상태를 한눈에 볼 수 있습니다.')

    tab_json,tab_csv,tab_result=st.tabs(['B. 불사자 JSON 일괄 수입','C. 검색 1P CSV 일괄 수입','D. 검증 결과'])
    with tab_json:
        st.caption('이전에 사용한 불사자 v0.6 JSON: 요약 지표와 agGrids 상품 목록이 있으면 함께 저장합니다. 옵션 중복 제거 매출이라고 판단하지 않습니다.')
        file=st.file_uploader('불사자 JSON (여러 키워드 records 지원)',type=['json'],key='bulsaja-upload')
        if file:
            try:
                raw=json.loads(file.getvalue())
                num_records=len(raw.get('records',[])) if isinstance(raw,dict) else len(raw)
                products,warnings=parse_bulsaja_products(raw)
                st.write(f'키워드 기록: **{num_records}개** / 분석 가능한 상품행: **{len(products)}개**')
                if warnings: st.info(' / '.join(warnings[:2]))
                if st.button('요약 + 상품행 저장',type='primary'):
                    result=import_bulsaja_json(conn,raw)
                    if products:
                        product_result=save_search_rows(conn,products,source='사용자 제공 불사자 v0.6 JSON')
                        st.success(f'시장요약 {result["imported"]}건 / 검색 상품 목록 {sum(z["count"] for z in product_result["snapshots"])}행 저장')
                    else: st.success(f'시장요약 {result["imported"]}건 저장. 상품 목록은 없음')
                    queue_keywords(conn,[x.get('keyword','') for x in (raw.get('records',[]) if isinstance(raw,dict) else raw) if isinstance(x,dict)])
                    st.rerun()
            except Exception as exc:st.error(f'불사자 JSON 확인 실패: {exc}')
    with tab_csv:
        st.caption('허용된 검색 결과 파일을 한 번에 여러 키워드로 저장합니다. 필수: keyword, rank, title. 기타 필드는 선택입니다.')
        with open('sample_data/search_1p_example.csv','rb') as f:
            st.download_button('1P 상품 CSV 예시 받기',f,'search_1p_example.csv','text/csv')
        file=st.file_uploader('1P 상품 목록 CSV',type=['csv'],key='search-csv')
        if file:
            try:
                parsed,warnings=parse_search_rows(parse_csv_bytes(file.getvalue()))
                st.write(f'유효 상품행 **{len(parsed)}개** / 검색 키워드 **{len(set(x["keyword"] for x in parsed))}개**')
                if warnings:st.warning(' / '.join(warnings[:3]))
                if parsed:st.dataframe(pd.DataFrame(parsed).head(40),hide_index=True,use_container_width=True)
                if st.button('검색 1P 상품행 저장',type='primary',disabled=not parsed):
                    result=save_search_rows(conn,parsed,source='사용자 제공 검색 1P CSV')
                    st.success(f'신규 {len(result["snapshots"])}개 키워드 측정 / {sum(x["count"] for x in result["snapshots"])}개 상품행. 동일 데이터 재업로드 {len(result["unchanged"])}개는 건너뜀')
                    st.rerun()
            except Exception as exc:st.error(f'1P CSV 확인 실패: {exc}')
    with tab_result:
        jobs=queue_rows(conn)
        if jobs:
            analyses=[evaluate_keyword(conn,j['keyword']) for j in jobs]
            df=pd.DataFrame([{
                '메인키워드':v['keyword'],'시장매출(추정)':v['market_revenue'],
                '시장규모':v['market_state'],'월검색량':v['monthly_search'],
                '검색 상품행':v['rows'],'독립 상품 추정':v['unique_products'],
                'TOP10 리뷰 평균(불사자)':v['top10_reviews_bulsaja'],
                '저리뷰(300개↓) TOP20':v['low_review_top20'],
                '대표판매가(중앙값)':v['median_price'],'상태':v['status']}
                for v in analyses])
            st.dataframe(df,hide_index=True,use_container_width=True)
            st.download_button('1P 검증 결과 CSV 다운로드',dicts_to_csv(df.where(pd.notnull(df),None).to_dict('records')),
                'search_1p_review.csv','text/csv')
            kw=st.selectbox('검증 세부 확인',list(v['keyword'] for v in analyses),key='detail-kw')
            ev=next(v for v in analyses if v['keyword']==kw)
            st.write('**추가 검증 필요:** '+(' · '.join(ev['issues']) if ev['issues'] else '기본 요약 항목 확인됨'))
            if ev['low_review_examples']:
                st.dataframe(pd.DataFrame(ev['low_review_examples'])[['rank','title','reviews','price','estimated_sales','estimated_revenue']],hide_index=True,use_container_width=True)
            matches=latest_search_products(conn,kw)
            if matches:st.dataframe(pd.DataFrame(matches)[['rank','title','price','reviews','estimated_sales','estimated_revenue']],hide_index=True,use_container_width=True)
        else:st.info('키워드를 대기열에 넣고 검증 자료를 추가하면 비교표가 나타납니다.')
        st.caption('순위 5~10위 판매량은 옵션 중복을 제거한 값이 아니므로 임의 합산하지 않습니다. 시장 매출과 실제 검색 결과는 별도 자료입니다.')

else:
    st.title('설정 및 사용법')
    st.markdown('''
#### 사용 순서
1. **카테고리 필터**에서 본인 로켓그로스 공식 카테고리 JSON/API 혹은 Excel/CSV를 가져옵니다.
2. 소형 생활용품 중 **적합** 카테고리를 확인하고, 대형·인증 위험·시즌성 높은 카테고리는 제외합니다.
3. **랭킹 40개 분석**에서 해당 카테고리의 허용된 상품 자료 CSV를 업로드합니다.
4. **메인키워드 DB**에서 후보를 보고, **검색 1P 검증**에서 불사자 JSON 데이터를 추가합니다.
5. 상위 후보만 1688에서 원가, 구성, 마진 및 포장 부피를 직접 확인합니다.

#### 프로그램 특징
- `127.0.0.1:8789`는 이 컴퓨터 내부 주소입니다. 외부 IP가 바뀌어도 그대로입니다.
- 데이터는 `app_data/sourcing.db`에 저장합니다. 재부팅·재실행 후에도 유지됩니다.
- 각 카테고리의 최신 랭킹 자료와 이전 작업 상태를 보관하여 중복 작업을 줄입니다.
- 자동 점수는 실제 매출·ROAS·순이익의 보증이 아닙니다.
- **모든 품목의 인증 면제를 주장하지 않습니다.** KC, 생활화학제품 등 요건은 개별 제품별로 확인해야 합니다.
- 브라우저 자동 순회·차단 우회 기능은 넣지 않았습니다.

#### 지원 파일 형태
- 카테고리: 공식 중첩 API JSON, 일부 평면 Excel/CSV (열 이름에 따라 추가 보정 필요)
- 상품: `category_code,rank,product_id,title,price,reviews,brand,delivery,url` CSV
- 불사자: 기존 수집기의 `records[].summary.fields` 및 `agGrids` 포함 JSON
- 검색 1P 결과: `keyword,rank,title,price,reviews,estimated_sales,estimated_revenue` CSV
''')
    st.markdown('[로켓그로스 카테고리 API 공식 문서](https://developers.coupang.com/ko/api/rocket-growth/how-to-get-category-list-for-rocket-growth-products)')
    st.markdown('[기존 구글 소싱 DB 열기](https://docs.google.com/spreadsheets/d/18D_zimerpl1km4reH-ExY_75TjM2M9D0dVtzKP7Oo5k/edit)')
    st.warning('구글 스프레드시트 직접 동기화는 2차 개발 범위입니다. 이번 버전은 키워드 CSV 내보내기를 제공합니다.')
    st.markdown('### 백업')
    st.download_button('현재 SQLite DB 백업 다운로드',database_backup(conn),'sourcing_backup.db','application/octet-stream')
    st.caption('배포 버전: MVP 0.4 · 자료 접근 권한이 확보된 입력 기반 분석기')

conn.close()
