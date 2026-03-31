from __future__ import annotations

import streamlit as st
from streamlit_autorefresh import st_autorefresh

from core.data import fetch_dashboard_bundle
from core.metrics import FilterState, build_filter_options, calculate_dashboard_state
from ui.render import inject_global_css, render_dashboard_html


REFRESH_MS = 5 * 60 * 1000

# ID da planilha Google Sheets
GSHEET_ID = "1bZsOLP2Yi0HdqytKgkT6s2c6P56W3vil_LqGNKVpzkE"

# Nome da aba principal + fallbacks caso a aba mude
CRONOGRAMA_SHEET = "base_demanda"
CRONOGRAMA_FALLBACKS = ("df_preparado", "CRONOGRAMA_GF&P", "base_demandas")


def hide_streamlit_chrome() -> None:
    st.markdown(
        """
        <style>
          html, body, [data-testid="stAppViewContainer"], [data-testid="stAppViewContainer"] > .main,
          [data-testid="stAppViewBlockContainer"], .block-container {
            margin: 0 !important;
            padding: 0 !important;
            background: #d9d9d9 !important;
            overflow: hidden !important;
          }
          #MainMenu { visibility: hidden; }
          footer { visibility: hidden; }
          header { visibility: hidden; }
          [data-testid="stHeader"] { display: none !important; }
          [data-testid="stToolbar"] { display: none !important; }
          [data-testid="stDecoration"] { display: none !important; }
          [data-testid="stStatusWidget"] { display: none !important; }
          [data-testid="stAppViewContainer"] { padding-top: 0 !important; }
          [data-testid="stAppViewBlockContainer"] { max-width: none !important; }
          [data-testid="stVerticalBlock"] > [style*="flex-direction: column;"] > [data-testid="stVerticalBlock"] {
            gap: 0 !important;
          }
          a[href*="streamlit.io"] { display: none !important; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _get_secret(key: str, default: str = "") -> str:
    try:
        value = st.secrets.get(key, default)
    except Exception:
        return default
    return str(value).strip() if value is not None else default


st.set_page_config(page_title="Dashboard de Cronogramas", layout="wide")
hide_streamlit_chrome()
inject_global_css()
st_autorefresh(interval=REFRESH_MS, key="dashboard-cronogramas-refresh")

# Permite sobrescrever via secrets.toml se necessário
gsheet_id = _get_secret("GSHEET_ID", GSHEET_ID)
cronograma_sheet = _get_secret("SHEETS_CRONOGRAMA_SHEET", CRONOGRAMA_SHEET)

bundle = fetch_dashboard_bundle(
    gsheet_id=gsheet_id,
    cronograma_sheet=cronograma_sheet,
    cronograma_fallbacks=CRONOGRAMA_FALLBACKS,
)

if not bundle.get("ok"):
    st.error(bundle.get("message") or "Falha ao carregar o Dashboard de Cronogramas.")
    st.json(bundle.get("details") or bundle)
    st.stop()

cronograma_records = bundle.get("datasets", {}).get("cronograma", [])
filter_options = build_filter_options(cronograma_records)

st.markdown(
    """
    <div class="filter-label-layer" aria-hidden="true">
      <div class="filter-fixed-label filter-fixed-label--consultor">Consultor:</div>
      <div class="filter-fixed-label filter-fixed-label--time">Time:</div>
      <div class="filter-fixed-label filter-fixed-label--cliente">Cliente:</div>
    </div>
    """,
    unsafe_allow_html=True,
)

consultor = st.selectbox(
    "Consultor",
    options=filter_options["consultor"],
    index=0,
    key="filtro_consultor",
    label_visibility="collapsed",
)

time = st.selectbox(
    "Time",
    options=filter_options["time"],
    index=0,
    key="filtro_time",
    label_visibility="collapsed",
)

cliente = st.selectbox(
    "Cliente",
    options=filter_options["cliente"],
    index=0,
    key="filtro_cliente",
    label_visibility="collapsed",
)

state = calculate_dashboard_state(
    resumo_records=bundle.get("datasets", {}).get("resumo", []),
    atualizacao_records=bundle.get("datasets", {}).get("atualizacao", []),
    atrasos_records=bundle.get("datasets", {}).get("atrasos", []),
    cronograma_records=cronograma_records,
    filters=FilterState(consultor=consultor, time=time, cliente=cliente),
)

st.markdown(
    render_dashboard_html(state=state, updated_at=bundle.get("updatedAt")),
    unsafe_allow_html=True,
)