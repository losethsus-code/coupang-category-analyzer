"""Single focus home screen. Other detailed analysis stays in advanced tools."""
import pandas as pd
import streamlit as st
from core import exported_keywords
from search_1p import queue_rows, search_url
from one_product import (current as focused_product, latest_history as one_product_history,
    start as start_one_product, update_notes as save_one_product,
    advance as advance_one_product, deadline_display, market_snapshot)

def render(conn):
    st.title('이번에 소싱할 상품 1개')
    st.caption('많이 분석하는 프로그램이 아니라, 72시간 안에 샘플을 진행할지 결정하는 도구입니다.')
    candidate=focused_product(conn)
    if not candidate:
        st.success('현재 진행 중인 상품이 없습니다. 먼저 하나만 선택하세요.')
        # 기존 키워드 DB가 있으면 추천 목록을 가져오지만, 파일이나 API는 필수가 아닙니다.
        known=list(dict.fromkeys(
            [x['keyword'] for x in exported_keywords(conn)] +
            [x['keyword'] for x in queue_rows(conn)]
        ))
        if known:
            choices=['직접 입력']+known[:100]
            chosen=st.selectbox('기존 DB에서 메인키워드 선택 (선택사항)',choices)
        else:
            chosen='직접 입력'
        with st.form('start-focus'):
            keyword=st.text_input('이번에 검토할 메인키워드',
                value='' if chosen=='직접 입력' else chosen,
                placeholder='예: 화장품정리함')
            problem=st.text_input('고객이 겪는 불편 (몰라도 비워두기)',placeholder='예: 화장품이 넘어지고 꺼내기 불편함')
            difference=st.text_input('눈에 보이는 개선 아이디어 (선택)',placeholder='예: 분리형 칸막이 + 낮은 높이')
            submit=st.form_submit_button('이 상품 1개부터 검토하기',type='primary')
        if submit:
            try:
                start_one_product(conn,keyword,problem,difference)
                st.rerun()
            except ValueError as exc:st.error(str(exc))
        st.caption('카테고리 전체를 먼저 조사할 필요는 없습니다. 쿠팡에서 발견한 키워드 하나만 있어도 시작할 수 있어요.')
    else:
        st.subheader(f'현재 집중 상품 · {candidate["keyword"]}')
        label,late=deadline_display(candidate)
        if late:st.warning(label)
        else:st.caption(label)
        stages=['발굴','시장확인','제조문의','샘플결정']
        if candidate['state'] in stages:
            st.progress((stages.index(candidate['state'])+1)/len(stages))
        snap=market_snapshot(conn,candidate['keyword'])
        if snap:
            cols=st.columns(3)
            cols[0].metric('불사자 1P 추정매출',f'{snap["first_page_revenue"] / 100000000:.2f}억' if snap['first_page_revenue'] is not None else '미확인')
            cols[1].metric('월 검색량',f'{snap["monthly_search"]:,}' if snap['monthly_search'] is not None else '미확인')
            cols[2].metric('TOP10 평균 리뷰',f'{snap["top10_reviews"]:,}' if snap['top10_reviews'] is not None else '미확인')
            st.caption('불사자 추정값 · 실제 판매량이나 진입 가능성을 확정하지 않습니다.')
        else:
            st.info('불사자 검증은 아직 없어도 괜찮아. 먼저 고객 불편과 제품 개선 아이디어부터 확인해봐.')
        st.markdown('### 핵심 3가지 질문')
        with st.form('one-product-notes'):
            problem=st.text_area('① 고객이 왜 이 상품을 필요로 하지?',value=candidate['problem'],height=70,
                placeholder='불편/구매 목적/경쟁사 리뷰 불만')
            difference=st.text_area('② 기존 제품과 무엇이 눈에 띄게 다르지?',value=candidate['difference'],height=70,
                placeholder='크기, 구조, 소재, 사용 장면, 구성 중 1개라도 개선')
            market_note=st.text_input('③ 쿠팡 시장은 어떤가? (한 문장)',value=candidate['market_note'],
                placeholder='예: 저리뷰 상품도 판매됨 / 시장 작음 / 아직 미확인')
            manufacturer_note=st.text_input('제조 문의·MOQ·예상 원가 메모 (선택)',value=candidate['manufacturer_note'],
                placeholder='예: 기존 금형 활용, 100개 시험 가능 여부 문의')
            st.caption('샘플 진행 전에 꼭 확인할 위험 3개. 체크는 실제로 확인한 경우에만.')
            a,b,c=st.columns(3)
            cert=a.checkbox('인증·규제 확인',value=bool(candidate['checks_cert']))
            cost=b.checkbox('원가·광고 전 마진 확인',value=bool(candidate['checks_cost']))
            shipping=c.checkbox('포장 부피·물류비 확인',value=bool(candidate['checks_shipping']))
            save=st.form_submit_button('기록 저장',type='primary')
        if save:
            save_one_product(conn,candidate['id'],problem=problem,difference=difference,
                market_note=market_note,manufacturer_note=manufacturer_note,
                checks_cert=cert,checks_cost=cost,checks_shipping=shipping)
            st.success('저장했어. PC를 껐다 켜도 유지돼.')
            st.rerun()
        st.markdown('### 다음 행동 하나 선택')
        stage_options=[x for x in stages if x!=candidate['state']]
        stage=st.selectbox('진행 단계',stage_options,
            index=stage_options.index('시장확인') if candidate['state']=='발굴' and '시장확인' in stage_options else 0)
        if st.button('다음 단계로 이동'):
            advance_one_product(conn,candidate['id'],stage)
            st.rerun()
        st.divider()
        dec1,dec2,dec3=st.columns(3)
        if dec1.button('샘플 진행 확정',type='primary',disabled=not(bool(candidate['checks_cert']) and bool(candidate['checks_cost']) and bool(candidate['checks_shipping'])),use_container_width=True):
            try:
                advance_one_product(conn,candidate['id'],'샘플주문')
                st.rerun()
            except ValueError as exc:st.error(str(exc))
        if dec2.button('보류하고 다른 상품 보기',use_container_width=True):
            advance_one_product(conn,candidate['id'],'보류')
            st.rerun()
        if dec3.button('탈락시키고 다음 상품',use_container_width=True):
            advance_one_product(conn,candidate['id'],'탈락')
            st.rerun()
        if not(candidate['checks_cert'] and candidate['checks_cost'] and candidate['checks_shipping']):
            st.caption('인증·원가·부피를 확인하고 [기록 저장]을 누르면 샘플 확정이 활성화돼. 보류/탈락은 언제든 가능해.')
        st.link_button('쿠팡 검색 1페이지 열기',search_url(candidate['keyword']))
    with st.expander('이전 검토 기록 (최대 10건)'):
        history=one_product_history(conn)
        if history:
            st.dataframe(pd.DataFrame([{'키워드':x['keyword'],'결과':x['state'],
                '차별화 아이디어':x['difference'],'시작일':x['created_at'][:10]} for x in history]),
                use_container_width=True,hide_index=True)
        else:st.caption('아직 이전 후보가 없어.')
    st.caption('ODM은 기존 제품 개선/샘플 검증부터. 새 금형·대량 주문은 실제 수요와 손익 확인 후 결정하세요.')
