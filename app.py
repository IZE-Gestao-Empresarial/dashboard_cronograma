from __future__ import annotations

import base64
from io import BytesIO

import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

from core.data import fetch_dashboard_bundle
from core.metrics import ALL_OPTION, FilterState, calculate_dashboard_state
from ui.render import inject_global_css, render_dashboard_html


REFRESH_MS = 5 * 60 * 1000

# ID da planilha Google Sheets
GSHEET_ID = "1bZsOLP2Yi0HdqytKgkT6s2c6P56W3vil_LqGNKVpzkE"

# Nome da aba principal + fallbacks caso a aba mude
CRONOGRAMA_SHEET = "base_demandas"
CRONOGRAMA_FALLBACKS = ("base_demanda", "df_preparado", "CRONOGRAMA_GF&P")


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




def _xlsx_download_href(rows: list[dict], columns: list[str]) -> str:
    df = pd.DataFrame(rows)
    if columns:
        for col in columns:
            if col not in df.columns:
                df[col] = ""
        df = df[columns]
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Detalhamento", index=False)
    encoded = base64.b64encode(output.getvalue()).decode("ascii")
    return "data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64," + encoded



def _records_df(records: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(records or [])


def _filtered_records_df(df: pd.DataFrame, *, consultor: str = ALL_OPTION, time: str = ALL_OPTION, cliente: str = ALL_OPTION) -> pd.DataFrame:
    work = df.copy()
    if work.empty:
        return work
    if consultor != ALL_OPTION and "responsavel" in work.columns:
        work = work[work["responsavel"].fillna("").astype(str) == consultor]
    if time != ALL_OPTION and "area" in work.columns:
        work = work[work["area"].fillna("").astype(str) == time]
    if cliente != ALL_OPTION and "empresa_gfp" in work.columns:
        work = work[work["empresa_gfp"].fillna("").astype(str) == cliente]
    return work


def _option_values(df: pd.DataFrame, column: str) -> list[str]:
    if df.empty or column not in df.columns:
        return [ALL_OPTION]
    values = sorted({str(v).strip() for v in df[column].dropna().tolist() if str(v).strip()}, key=lambda x: x.casefold())
    return [ALL_OPTION, *values]


def _dependent_filter_options(df: pd.DataFrame, *, consultor: str, time: str, cliente: str) -> dict[str, list[str]]:
    consultor_df = _filtered_records_df(df, time=time, cliente=cliente)
    time_df = _filtered_records_df(df, consultor=consultor, cliente=cliente)
    cliente_df = _filtered_records_df(df, consultor=consultor, time=time)
    return {
        "consultor": _option_values(consultor_df, "responsavel"),
        "time": _option_values(time_df, "area"),
        "cliente": _option_values(cliente_df, "empresa_gfp"),
    }


def _ensure_valid_filter_value(key: str, options: list[str]) -> str:
    current = str(st.session_state.get(key, ALL_OPTION) or ALL_OPTION)
    if current not in options:
        st.session_state[key] = ALL_OPTION
        return ALL_OPTION
    return current


def _attach_detail_downloads(state: dict) -> dict:
    details = state.get("details", {}) or {}
    for detail in details.values():
        rows = detail.get("download_rows") or detail.get("rows") or []
        columns = detail.get("columns") or []
        detail["download_href"] = _xlsx_download_href(rows, columns)
    return state


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
cronograma_df = _records_df(cronograma_records)

current_consultor = str(st.session_state.get("filtro_consultor", ALL_OPTION) or ALL_OPTION)
current_time = str(st.session_state.get("filtro_time", ALL_OPTION) or ALL_OPTION)
current_cliente = str(st.session_state.get("filtro_cliente", ALL_OPTION) or ALL_OPTION)

filter_options = _dependent_filter_options(
    cronograma_df,
    consultor=current_consultor,
    time=current_time,
    cliente=current_cliente,
)

_ensure_valid_filter_value("filtro_consultor", filter_options["consultor"])
_ensure_valid_filter_value("filtro_time", filter_options["time"])
_ensure_valid_filter_value("filtro_cliente", filter_options["cliente"])

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
    key="filtro_consultor",
    label_visibility="collapsed",
)

time = st.selectbox(
    "Time",
    options=filter_options["time"],
    key="filtro_time",
    label_visibility="collapsed",
)

cliente = st.selectbox(
    "Cliente",
    options=filter_options["cliente"],
    key="filtro_cliente",
    label_visibility="collapsed",
)

state = _attach_detail_downloads(calculate_dashboard_state(
    resumo_records=bundle.get("datasets", {}).get("resumo", []),
    atualizacao_records=bundle.get("datasets", {}).get("atualizacao", []),
    atrasos_records=bundle.get("datasets", {}).get("atrasos", []),
    cronograma_records=cronograma_records,
    filters=FilterState(consultor=consultor, time=time, cliente=cliente),
))

st.markdown(
    render_dashboard_html(state=state, updated_at=bundle.get("updatedAt")),
    unsafe_allow_html=True,
)