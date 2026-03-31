from __future__ import annotations

from pathlib import Path
from typing import Any
import urllib.parse
from io import StringIO

import pandas as pd
import requests
import streamlit as st


DEFAULT_TIMEOUT = 25
CACHE_TTL_SECONDS = 240
PROJECT_ROOT = Path(__file__).resolve().parent.parent


# -----------------------------
# Google Sheets
# -----------------------------

def _gsheet_csv_url(spreadsheet_id: str, sheet_name: str) -> str:
    encoded = urllib.parse.quote(sheet_name)
    return (
        f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"
        f"/gviz/tq?tqx=out:csv&sheet={encoded}"
    )


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def _fetch_gsheet(spreadsheet_id: str, sheet_name: str) -> dict[str, Any]:
    url = _gsheet_csv_url(spreadsheet_id, sheet_name)
    response = requests.get(url, timeout=DEFAULT_TIMEOUT)
    response.raise_for_status()
    df = pd.read_csv(StringIO(response.text))
    return {
        "ok": True,
        "sheet": sheet_name,
        "spreadsheetName": f"GoogleSheets:{spreadsheet_id}",
        "rows": df.to_dict(orient="records"),
    }


# -----------------------------
# Normalização de payloads
# -----------------------------

def extract_records(payload: Any) -> list[dict[str, Any]]:
    if payload is None:
        return []
    if isinstance(payload, pd.DataFrame):
        return payload.to_dict(orient="records")
    if isinstance(payload, list):
        if not payload:
            return []
        if all(isinstance(item, dict) for item in payload):
            return payload
        return [{"value": item} for item in payload]
    if not isinstance(payload, dict):
        return []
    for key in ("rows", "data", "records", "items", "values"):
        if key in payload:
            return extract_records(payload[key])
    scalar_keys = set(payload.keys()) - {"ok", "message", "error", "status_code", "text", "sheet", "spreadsheetName", "updatedAt"}
    if scalar_keys:
        return [payload]
    return []


def dataframe_from_payload(payload: Any) -> pd.DataFrame:
    records = extract_records(payload)
    if not records:
        return pd.DataFrame()
    return pd.DataFrame(records)


# -----------------------------
# Normalização do cronograma
# -----------------------------

def _coalesce(df: pd.DataFrame, *columns: str, default: Any = None) -> pd.Series:
    result = pd.Series([default] * len(df), index=df.index, dtype="object")
    for column in columns:
        if column in df.columns:
            series = df[column]
            mask = result.isna() | (result.astype(str).str.strip() == "") | (result == default)
            result = result.where(~mask, series)
    return result


def _clean_string_series(series: pd.Series) -> pd.Series:
    return (
        series.fillna("")
        .astype(str)
        .str.replace(r"\s+", " ", regex=True)
        .str.strip()
    )


def _to_datetime(series: pd.Series) -> pd.Series:
    dt = pd.to_datetime(series, errors="coerce")
    try:
        if getattr(dt.dt, "tz", None) is not None:
            dt = dt.dt.tz_convert("America/Sao_Paulo").dt.tz_localize(None)
    except Exception:
        pass
    return dt


GROUP_TO_CATEGORY = {
    "Organização Básica": "Base",
    "Software de Gestão Financeira": "Base",
    "Análises": "Análises",
    "Relatórios Essenciais e Indicadores": "Análises",
    "Planejamento Estratégico": "Planejamento",
    "Planejamento Financeiro": "Planejamento",
    "Acompanhamento do Primeiro Ciclo de Planejamento": "Extras",
    "Demandas Extras": "Extras",
    "EXTRAS": "Extras",
    "Processos e Manuais de Rotina Financeira": "Extras",
    "Revisão e Construção do Segundo Ciclo de Planejamento": "Extras",
    "Revisão e Maturação da Gestão Financeira": "Extras",
    "Rotina Mensal": "Extras",
    "Diagnóstico e Padronização": "Diagnóstico",
    "Cronograma Atual": "_cronograma",
}


def _infer_category(grupo_nome: str, grupo_anterior: str) -> str:
    grupo_nome = (grupo_nome or "").strip()
    grupo_anterior = (grupo_anterior or "").strip()
    base_source = grupo_anterior if grupo_nome == "Finalizadas" else grupo_nome
    if base_source == "[sem movimentação registrada]" and grupo_nome == "Finalizadas":
        return "_finalizadas_sem_origem"
    if base_source in GROUP_TO_CATEGORY:
        return GROUP_TO_CATEGORY[base_source]
    if not base_source:
        return "_outros"
    return "_outros"


def prepare_cronograma_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=[
            "empresa_gfp", "responsavel", "area", "meses_na_ize",
            "item_nome", "grupo_nome", "grupo_anterior", "status",
            "categoria", "finalizada", "ultima_atualizacao_dt",
            "previsao_dt", "em_atraso", "dias_atraso",
        ])

    work = df.copy()
    work.columns = [str(col).strip() for col in work.columns]

    # Mapeia colunas do Sheets para os nomes internos esperados
    # grupo_atual → grupo_nome
    # ultima_atualizacao → ultima_atualizacao_dt
    # previsao_entrega → previsao_dt

    empresa = _clean_string_series(_coalesce(work, "empresa_gfp", "cliente", default=""))
    responsavel = _clean_string_series(_coalesce(work, "responsavel", "consultor", default=""))
    area = _clean_string_series(_coalesce(work, "area", "time", "team", default=""))
    meses = pd.to_numeric(_coalesce(work, "meses_na_ize", "meses", default=None), errors="coerce")
    item_nome = _clean_string_series(_coalesce(work, "item_nome", "elemento", "ultima_etapa", default=""))
    grupo_nome = _clean_string_series(_coalesce(work, "grupo_atual", "grupo_nome", default=""))
    grupo_anterior = _clean_string_series(_coalesce(work, "grupo_anterior", default=""))
    status = _clean_string_series(_coalesce(work, "status", default=""))

    previsao_dt = _to_datetime(_coalesce(work, "previsao_entrega", "previsao_dt", default=None))
    ultima_atualizacao_dt = _to_datetime(_coalesce(work, "ultima_atualizacao", "ultima_atualizacao_dt", "data_atualizacao", default=None))

    out = pd.DataFrame({
        "empresa_gfp": empresa,
        "responsavel": responsavel,
        "area": area,
        "meses_na_ize": meses,
        "item_nome": item_nome,
        "grupo_nome": grupo_nome,
        "grupo_anterior": grupo_anterior,
        "status": status,
        "previsao_dt": previsao_dt,
        "ultima_atualizacao_dt": ultima_atualizacao_dt,
    })

    if "categoria" in work.columns:
        out["categoria"] = _clean_string_series(work["categoria"])
    else:
        out["categoria"] = [
            _infer_category(gn, ga)
            for gn, ga in zip(out["grupo_nome"], out["grupo_anterior"])
        ]

    if "finalizada" in work.columns:
        raw = work["finalizada"]
        out["finalizada"] = raw.map(
            lambda v: str(v).strip().lower() in {"true", "1", "sim", "yes"} if pd.notna(v) else False
        )
    else:
        out["finalizada"] = (out["grupo_nome"] == "Finalizadas") | (out["status"] == "Feito")

    today = pd.Timestamp.now(tz="America/Sao_Paulo").tz_localize(None).normalize()
    out["dias_atraso"] = (today - out["previsao_dt"].dt.normalize()).dt.days

    out["em_atraso"] = (
        out["previsao_dt"].notna()
        & (~out["finalizada"])
        & (out["dias_atraso"] > 0)
    )
    out["dias_atraso"] = out["dias_atraso"].where(out["em_atraso"], other=0)
    out["meses_na_ize"] = pd.to_numeric(out["meses_na_ize"], errors="coerce").astype(float)

    out = out[out["empresa_gfp"] != ""]
    out["ultima_etapa"] = out["item_nome"]
    out["empresa_gfp_clean"] = out["empresa_gfp"]
    return out.reset_index(drop=True)


# -----------------------------
# Bundle principal — tudo do Google Sheets
# -----------------------------

@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def fetch_dashboard_bundle(
    *,
    gsheet_id: str,
    cronograma_sheet: str,
    cronograma_fallbacks: tuple[str, ...] = (),
) -> dict[str, Any]:
    """
    Lê tudo do Google Sheets.
    Resumo, atualizacao e atrasos são derivados diretamente do cronograma,
    sem necessidade de abas separadas.
    """
    try:
        # Tenta a aba preferida, depois os fallbacks
        cron_payload = None
        cron_sheet_used = cronograma_sheet
        last_error: Exception | None = None

        for sheet in (cronograma_sheet, *cronograma_fallbacks):
            sheet = str(sheet or "").strip()
            if not sheet:
                continue
            try:
                payload = _fetch_gsheet(gsheet_id, sheet)
                records = extract_records(payload)
                if records:
                    cron_payload = payload
                    cron_sheet_used = sheet
                    break
            except Exception as exc:
                last_error = exc
                continue

        if cron_payload is None:
            if last_error:
                raise last_error
            raise RuntimeError("Nenhuma aba do cronograma retornou dados.")

        cronograma_df = prepare_cronograma_dataframe(dataframe_from_payload(cron_payload))

        # Deriva updated_at do próprio cronograma
        updated_at = ""
        if "ultima_atualizacao_dt" in cronograma_df.columns and not cronograma_df.empty:
            parsed = pd.to_datetime(cronograma_df["ultima_atualizacao_dt"], errors="coerce")
            if parsed.notna().any():
                updated_at = pd.Timestamp(parsed.max()).strftime("%d/%m/%Y %H:%M")

        # Gera resumo calculado dinamicamente a partir do cronograma
        resumo_records = _build_resumo(cronograma_df)

        # Gera atualizacao: top 3 itens mais recentemente atualizados
        atualizacao_records = _build_atualizacao(cronograma_df)

        # Gera atrasos: agrupado por empresa
        atrasos_records = _build_atrasos(cronograma_df)

        return {
            "ok": True,
            "datasets": {
                "resumo": resumo_records,
                "atualizacao": atualizacao_records,
                "atrasos": atrasos_records,
                "cronograma": cronograma_df.to_dict(orient="records"),
            },
            "updatedAt": updated_at,
            "sheetNames": {"cronograma": cron_sheet_used},
            "spreadsheetName": cron_payload.get("spreadsheetName", "Dashboard de Cronogramas"),
        }

    except requests.HTTPError as exc:
        resp = exc.response
        return {
            "ok": False,
            "message": f"Erro HTTP ao consultar o Google Sheets: {exc}",
            "details": {"status_code": resp.status_code if resp is not None else None},
        }
    except requests.RequestException as exc:
        return {"ok": False, "message": f"Erro de conexão: {exc}"}
    except Exception as exc:
        return {"ok": False, "message": f"Erro inesperado: {exc}"}


# -----------------------------
# Derivações internas
# -----------------------------

CONCLUSION_CATEGORIES = ["Base", "Análises", "Planejamento", "Extras"]


def _build_resumo(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Gera os registros de resumo calculados a partir do cronograma."""
    records = []

    for category in CONCLUSION_CATEGORIES:
        cat_df = df[df["categoria"].fillna("") == category]
        total = len(cat_df)
        finalizadas = int(cat_df["finalizada"].fillna(False).sum()) if total else 0
        pct = (finalizadas / total * 100.0) if total else 0.0
        label_map = {
            "Base": "% conclusão — Base",
            "Análises": "% conclusão — Análises",
            "Planejamento": "% conclusão — Planejamento",
            "Extras": "% conclusão — Extras",
        }
        records.append({"indicador": label_map[category], "valor": pct})

    # Tempo médio
    unique_clients = df[["empresa_gfp", "meses_na_ize"]].drop_duplicates(subset=["empresa_gfp"])
    tempo_medio = float(unique_clients["meses_na_ize"].dropna().mean()) if not unique_clients.empty else 0.0
    records.append({"indicador": "Tempo médio clientes (meses)", "valor": tempo_medio})

    # Demandas no cronograma (categoria _cronograma)
    cron_df = df[df["categoria"].fillna("") == "_cronograma"]
    if not cron_df.empty:
        per_client = cron_df.groupby("empresa_gfp").size()
        media = float(per_client.mean()) if not per_client.empty else 0.0
        menos_3 = int((per_client < 3).sum()) if not per_client.empty else 0
    else:
        media = 0.0
        menos_3 = 0
    records.append({"indicador": "Média por cliente (cronograma)", "valor": media})
    records.append({"indicador": "Clientes abaixo do mínimo", "valor": menos_3})

    # Finalizadas / pendentes
    finalizadas_total = int(df["finalizada"].fillna(False).sum())
    pending_mask = (
        (~df["finalizada"].fillna(False))
        & (~df["categoria"].fillna("").isin(["_outros", "_cronograma"]))
    )
    pendentes = int(pending_mask.sum())
    records.append({"indicador": "Demandas finalizadas (total)", "valor": finalizadas_total})
    records.append({"indicador": "Demandas pendentes", "valor": pendentes})

    return records


def _build_atualizacao(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Top 3 itens mais recentemente atualizados."""
    if df.empty or "ultima_atualizacao_dt" not in df.columns:
        return []
    work = df.copy()
    work = work.sort_values("ultima_atualizacao_dt", ascending=False, na_position="last")
    latest = work.groupby("empresa_gfp", as_index=False).first()
    latest = latest.sort_values("ultima_atualizacao_dt", ascending=False, na_position="last")
    return [
        {
            "empresa_gfp": str(row.get("empresa_gfp") or ""),
            "empresa_gfp_clean": str(row.get("empresa_gfp_clean") or row.get("empresa_gfp") or ""),
            "ultima_etapa": str(row.get("ultima_etapa") or row.get("item_nome") or ""),
            # metrics.py usa data_atualizacao — fornecemos aqui mapeado
            "data_atualizacao": row.get("ultima_atualizacao_dt"),
        }
        for row in latest.head(3).to_dict(orient="records")
    ]


def _build_atrasos(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Atrasos agrupados por empresa."""
    if df.empty or "em_atraso" not in df.columns:
        return []
    delayed = df[df["em_atraso"].fillna(False)].copy()
    if delayed.empty:
        return []
    grouped = (
        delayed.groupby("empresa_gfp", as_index=False)
        .agg(qtd_atraso=("empresa_gfp", "size"), max_dias_atraso=("dias_atraso", "max"))
        .sort_values(["max_dias_atraso", "qtd_atraso"], ascending=[False, False])
    )
    return [
        {
            "empresa_gfp": str(row.get("empresa_gfp") or ""),
            "empresa_gfp_clean": str(row.get("empresa_gfp") or ""),
            "qtd_atraso": int(row.get("qtd_atraso") or 0),
            "max_dias_atraso": int(row.get("max_dias_atraso") or 0),
        }
        for row in grouped.to_dict(orient="records")
    ]