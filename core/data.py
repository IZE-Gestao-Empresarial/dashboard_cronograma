from __future__ import annotations

from pathlib import Path
from typing import Any
import math
import re

import pandas as pd
import requests
import streamlit as st


DEFAULT_TIMEOUT = 25
CACHE_TTL_SECONDS = 240
PROJECT_ROOT = Path(__file__).resolve().parent.parent


# -----------------------------
# Requests / source loading
# -----------------------------

def _safe_json(resp: requests.Response) -> dict[str, Any]:
    try:
        data = resp.json()
        return data if isinstance(data, dict) else {"ok": True, "data": data}
    except Exception:
        return {
            "ok": False,
            "message": "Resposta não-JSON do endpoint.",
            "status_code": resp.status_code,
            "text": resp.text[:1000],
        }


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def _fetch_sheet(url: str, token: str, sheet: str) -> dict[str, Any]:
    response = requests.get(
        url,
        params={"token": token, "sheet": sheet},
        timeout=DEFAULT_TIMEOUT,
    )
    response.raise_for_status()
    payload = _safe_json(response)
    payload.setdefault("sheet", sheet)
    return payload


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def _read_local_excel(path: str, sheet: str) -> dict[str, Any]:
    file_path = Path(path)
    if not file_path.is_absolute():
        file_path = PROJECT_ROOT / file_path

    if not file_path.exists():
        raise FileNotFoundError(f"Arquivo local não encontrado: {file_path}")

    df = pd.read_excel(file_path, sheet_name=sheet)
    return {
        "ok": True,
        "sheet": sheet,
        "spreadsheetName": file_path.stem,
        "rows": df.to_dict(orient="records"),
    }


# -----------------------------
# Normalização de payloads
# -----------------------------

def _normalize_header_cell(value: Any) -> str:
    text = str(value if value is not None else "").strip()
    return text



def _records_from_matrix(matrix: list[Any]) -> list[dict[str, Any]]:
    if not matrix:
        return []

    first = matrix[0]
    if not isinstance(first, list):
        return []

    headers = [_normalize_header_cell(cell) or f"col_{idx + 1}" for idx, cell in enumerate(first)]
    records: list[dict[str, Any]] = []

    for row in matrix[1:]:
        if not isinstance(row, list):
            continue
        record: dict[str, Any] = {}
        for idx, header in enumerate(headers):
            record[header] = row[idx] if idx < len(row) else None
        records.append(record)

    return records



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
        if all(isinstance(item, list) for item in payload):
            return _records_from_matrix(payload)
        return [{"value": item} for item in payload]

    if not isinstance(payload, dict):
        return []

    for key in ("rows", "data", "records", "items", "values"):
        if key in payload:
            return extract_records(payload.get(key))

    # payload já pode ser um único registro
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
        return pd.DataFrame(
            columns=[
                "empresa_gfp",
                "responsavel",
                "area",
                "meses_na_ize",
                "item_nome",
                "grupo_nome",
                "grupo_anterior",
                "status",
                "categoria",
                "finalizada",
                "ultima_atualizacao_dt",
                "previsao_dt",
                "em_atraso",
                "dias_atraso",
            ]
        )

    work = df.copy()
    work.columns = [str(col).strip() for col in work.columns]

    empresa = _clean_string_series(_coalesce(work, "empresa_gfp", "empresa_gfp_clean", "cliente", default=""))
    responsavel = _clean_string_series(_coalesce(work, "responsavel", "consultor", "owner", default=""))
    area = _clean_string_series(_coalesce(work, "area", "time", "team", default=""))
    meses = pd.to_numeric(_coalesce(work, "meses_na_ize", "meses", default=None), errors="coerce")
    item_nome = _clean_string_series(_coalesce(work, "item_nome", "elemento", "ultima_etapa", default=""))
    grupo_nome = _clean_string_series(_coalesce(work, "grupo_nome", "grupo_atual", default=""))
    grupo_anterior = _clean_string_series(_coalesce(work, "grupo_anterior", default=""))
    status = _clean_string_series(_coalesce(work, "status", default=""))

    previsao_dt = _to_datetime(_coalesce(work, "previsao_dt", "previsao_entrega", default=None))
    ultima_atualizacao_dt = _to_datetime(_coalesce(work, "ultima_atualizacao_dt", "ultima_atualizacao", "data_atualizacao", default=None))

    out = pd.DataFrame(
        {
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
        }
    )

    if "categoria" in work.columns:
        out["categoria"] = _clean_string_series(work["categoria"])
    else:
        out["categoria"] = [
            _infer_category(gn, ga)
            for gn, ga in zip(out["grupo_nome"], out["grupo_anterior"])
        ]

    if "finalizada" in work.columns:
        raw_finalizada = work["finalizada"]
        out["finalizada"] = raw_finalizada.map(lambda v: str(v).strip().lower() in {"true", "1", "sim", "yes"} if pd.notna(v) else False)
        out.loc[raw_finalizada.map(lambda v: isinstance(v, bool)), "finalizada"] = raw_finalizada[raw_finalizada.map(lambda v: isinstance(v, bool))]
    else:
        out["finalizada"] = (out["grupo_nome"] == "Finalizadas") | (out["status"] == "Feito")

    today = pd.Timestamp.now(tz="America/Sao_Paulo").tz_localize(None).normalize()

    if "dias_atraso" in work.columns:
        out["dias_atraso"] = pd.to_numeric(work["dias_atraso"], errors="coerce")
    else:
        out["dias_atraso"] = (today - out["previsao_dt"].dt.normalize()).dt.days

    if "em_atraso" in work.columns:
        raw_em_atraso = work["em_atraso"]
        out["em_atraso"] = raw_em_atraso.map(lambda v: str(v).strip().lower() in {"true", "1", "sim", "yes"} if pd.notna(v) else False)
        out.loc[raw_em_atraso.map(lambda v: isinstance(v, bool)), "em_atraso"] = raw_em_atraso[raw_em_atraso.map(lambda v: isinstance(v, bool))]
    else:
        out["em_atraso"] = (
            out["previsao_dt"].notna()
            & (~out["finalizada"])
            & (out["dias_atraso"] > 0)
        )

    out["dias_atraso"] = out["dias_atraso"].where(out["em_atraso"], other=0)
    out["meses_na_ize"] = out["meses_na_ize"].astype(float)

    # Higienização final
    out = out[(out["empresa_gfp"] != "")]
    out["ultima_etapa"] = out["item_nome"]
    out["empresa_gfp_clean"] = out["empresa_gfp"]
    return out.reset_index(drop=True)


# -----------------------------
# Bundle principal
# -----------------------------

def _fetch_or_local(
    *,
    url: str,
    token: str,
    sheet: str,
    local_file: str = "",
) -> dict[str, Any]:
    if url and token:
        return _fetch_sheet(url, token, sheet)
    if local_file:
        return _read_local_excel(local_file, sheet)
    raise RuntimeError("Fonte de dados não configurada.")



def _first_non_empty(*values: str) -> str:
    for value in values:
        if str(value or "").strip():
            return str(value).strip()
    return ""



def _pick_working_sheet(
    *,
    url: str,
    token: str,
    preferred: str,
    fallbacks: list[str],
    local_file: str = "",
) -> tuple[str, dict[str, Any]]:
    tried: list[str] = []
    candidates = [preferred, *fallbacks]
    last_error: Exception | None = None

    for sheet in candidates:
        sheet = str(sheet or "").strip()
        if not sheet or sheet in tried:
            continue
        tried.append(sheet)
        try:
            payload = _fetch_or_local(url=url, token=token, sheet=sheet, local_file=local_file)
            records = extract_records(payload)
            if records or payload.get("ok", True):
                return sheet, payload
        except Exception as exc:  # pragma: no cover - fallback control
            last_error = exc
            continue

    if last_error is not None:
        raise last_error
    raise RuntimeError(f"Nenhuma aba válida encontrada entre: {', '.join(tried)}")


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def fetch_dashboard_bundle(
    *,
    url: str,
    token: str,
    resumo_sheet: str,
    atualizacao_sheet: str,
    atrasos_sheet: str,
    cronograma_sheet: str,
    cronograma_fallbacks: tuple[str, ...] = (),
    local_base_file: str = "",
    local_cronograma_file: str = "",
) -> dict[str, Any]:
    try:
        resumo_payload = _fetch_or_local(url=url, token=token, sheet=resumo_sheet, local_file=local_base_file)
        atualizacao_payload = _fetch_or_local(url=url, token=token, sheet=atualizacao_sheet, local_file=local_base_file)
        atrasos_payload = _fetch_or_local(url=url, token=token, sheet=atrasos_sheet, local_file=local_base_file)

        cron_sheet_used, cron_payload = _pick_working_sheet(
            url=url,
            token=token,
            preferred=cronograma_sheet,
            fallbacks=list(cronograma_fallbacks),
            local_file=_first_non_empty(local_cronograma_file, local_base_file),
        )

        resumo_df = dataframe_from_payload(resumo_payload)
        atualizacao_df = dataframe_from_payload(atualizacao_payload)
        atrasos_df = dataframe_from_payload(atrasos_payload)
        cronograma_df = prepare_cronograma_dataframe(dataframe_from_payload(cron_payload))

        updated_candidates: list[pd.Timestamp] = []
        for df, col in (
            (atualizacao_df, "data_atualizacao"),
            (cronograma_df, "ultima_atualizacao_dt"),
        ):
            if col in df.columns and not df.empty:
                parsed = pd.to_datetime(df[col], errors="coerce")
                if parsed.notna().any():
                    updated_candidates.append(parsed.max())

        updated_at = ""
        if updated_candidates:
            max_dt = max(updated_candidates)
            if pd.notna(max_dt):
                updated_at = pd.Timestamp(max_dt).strftime("%d/%m/%Y %H:%M")

        return {
            "ok": True,
            "datasets": {
                "resumo": resumo_df.to_dict(orient="records"),
                "atualizacao": atualizacao_df.to_dict(orient="records"),
                "atrasos": atrasos_df.to_dict(orient="records"),
                "cronograma": cronograma_df.to_dict(orient="records"),
            },
            "updatedAt": updated_at,
            "sheetNames": {
                "resumo": resumo_sheet,
                "atualizacao": atualizacao_sheet,
                "atrasos": atrasos_sheet,
                "cronograma": cron_sheet_used,
            },
            "spreadsheetName": (
                resumo_payload.get("spreadsheetName")
                or cron_payload.get("spreadsheetName")
                or "Dashboard de Cronogramas"
            ),
        }
    except requests.HTTPError as exc:
        response = exc.response
        details = _safe_json(response) if response is not None else {}
        return {
            "ok": False,
            "message": f"Erro HTTP ao consultar a API: {exc}",
            "details": details,
        }
    except requests.RequestException as exc:
        return {
            "ok": False,
            "message": f"Erro de conexão ao consultar a API: {exc}",
        }
    except Exception as exc:
        return {
            "ok": False,
            "message": f"Erro inesperado ao carregar o dashboard: {exc}",
        }
