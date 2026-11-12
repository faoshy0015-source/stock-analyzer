"""Shared navigation labels for Stock Analyzer Streamlit pages.

Built-in navigation is disabled in .streamlit/config.toml so the entrypoint
app.py can be displayed to users as Analyze without renaming it or breaking
the existing Community Cloud deployment entrypoint.
"""
from __future__ import annotations


def render_navigation(st):
    with st.sidebar:
        st.page_link("pages/2_시장_대시보드.py",
                     label="시장 대시보드", icon="📊")
        st.page_link("app.py", label="Analyze", icon="🔎")
        st.page_link("pages/0_전종목_수급_레이더.py",
                     label="전종목 수급 레이더", icon="📡")
        st.page_link("pages/1_수급_전환_검색.py",
                     label="수급 전환 검색", icon="🔄")
        st.divider()
