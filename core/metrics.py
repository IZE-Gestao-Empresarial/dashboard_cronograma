from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd


ALL_OPTION = "Todos"
CONCLUSION_ORDER = ["Base", "Análises", "Planejamento", "Extras"]
CONCLUSION_INDICATORS = {
    "Base": "% conclusão — Base",
    "Análises": "% conclusão — Análises",
    "Planejamento": "% conclusão — Planejamento",
    "Extras": "% conclusão — Extras",
}


@dataclass
class FilterState:
    consultor: str = ALL_OPTION
    time: str = ALL_OPTION
    cliente: str = ALL_OPTION

    @property
    def is_all(self) -> bool:
        return self.consultor == ALL_OPTION and self.time == ALL_OPTION and self.cliente == ALL_OPTION



def _to_df(records: list[dict[str, Any]] | None) -> pd.DataFrame:
    return pd.DataFrame(records or [])



def _text(value: Any) -> str:
    return str(value or "").strip()



def _normalize_resumo_value(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)

    text = _text(value).replace("%", "").replace(" ", "")
    if not text:
        return 0.0

    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")

    try:
        return float(text)
    except ValueError:
        return 0.0



def build_filter_options(cronograma_records: list[dict[str, Any]]) -> dict[str, list[str]]:
    df = _to_df(cronograma_records)
    if df.empty:
        return {
            "consultor": [ALL_OPTION],
            "time": [ALL_OPTION],
            "cliente": [ALL_OPTION],
        }

    def _options(column: str) -> list[str]:
        if column not in df.columns:
            return [ALL_OPTION]
        values = sorted({_text(v) for v in df[column].dropna().tolist() if _text(v)}, key=lambda x: x.casefold())
        return [ALL_OPTION, *values]

    return {
        "consultor": _options("responsavel"),
        "time": _options("area"),
        "cliente": _options("empresa_gfp"),
    }



def apply_filters(cronograma_records: list[dict[str, Any]], filters: FilterState) -> pd.DataFrame:
    df = _to_df(cronograma_records)
    if df.empty:
        return df

    if filters.consultor != ALL_OPTION:
        df = df[df["responsavel"].fillna("").astype(str) == filters.consultor]
    if filters.time != ALL_OPTION:
        df = df[df["area"].fillna("").astype(str) == filters.time]
    if filters.cliente != ALL_OPTION:
        df = df[df["empresa_gfp"].fillna("").astype(str) == filters.cliente]
    return df.reset_index(drop=True)



def _resumo_lookup(resumo_records: list[dict[str, Any]]) -> dict[str, float]:
    resumo = {}
    for row in resumo_records or []:
        indicador = _text(row.get("indicador"))
        if indicador:
            resumo[indicador] = _normalize_resumo_value(row.get("valor"))
    return resumo



def _format_stage_rows(df: pd.DataFrame, limit: int = 3) -> list[dict[str, Any]]:
    if df.empty:
        return []

    work = df.copy()
    work["data_atualizacao"] = pd.to_datetime(work["data_atualizacao"], errors="coerce")
    company_col = "empresa_gfp_clean" if "empresa_gfp_clean" in work.columns else "empresa_gfp"
    stage_col = "ultima_etapa" if "ultima_etapa" in work.columns else "item_nome"

    available = [company_col, stage_col, "data_atualizacao"]
    work = work[[col for col in available if col in work.columns]].copy()
    work = work.sort_values("data_atualizacao", ascending=False, na_position="last")
    return [
        {
            "cliente": _text(row.get(company_col)),
            "etapa": _text(row.get(stage_col)),
        }
        for row in work.head(limit).to_dict(orient="records")
    ]



def _format_delay_rows(df: pd.DataFrame, limit: int = 4) -> list[dict[str, Any]]:
    if df.empty:
        return []

    work = df.copy()
    company_col = "empresa_gfp_clean" if "empresa_gfp_clean" in work.columns else "empresa_gfp"
    work = work[[col for col in [company_col, "qtd_atraso", "max_dias_atraso"] if col in work.columns]].copy()
    work = work.sort_values(["max_dias_atraso", "qtd_atraso", company_col], ascending=[False, False, True], na_position="last")
    return [
        {
            "cliente": _text(row.get(company_col)),
            "demandas": int(float(row.get("qtd_atraso") or 0)),
            "dias": int(float(row.get("max_dias_atraso") or 0)),
        }
        for row in work.head(limit).to_dict(orient="records")
    ]



def _build_filtered_updates(filtered_df: pd.DataFrame) -> list[dict[str, Any]]:
    if filtered_df.empty:
        return []

    work = filtered_df.copy()
    work = work.sort_values("ultima_atualizacao_dt", ascending=False, na_position="last")
    latest = work.groupby("empresa_gfp", as_index=False).first()
    latest = latest.sort_values("ultima_atualizacao_dt", ascending=False, na_position="last")
    return [
        {
            "cliente": _text(row.get("empresa_gfp")),
            "etapa": _text(row.get("ultima_etapa") or row.get("item_nome")),
        }
        for row in latest.head(3).to_dict(orient="records")
    ]



def _build_filtered_delays(filtered_df: pd.DataFrame) -> list[dict[str, Any]]:
    if filtered_df.empty or "em_atraso" not in filtered_df.columns:
        return []

    delayed = filtered_df[filtered_df["em_atraso"].fillna(False)].copy()
    if delayed.empty:
        return []

    grouped = (
        delayed.groupby("empresa_gfp", as_index=False)
        .agg(qtd_atraso=("empresa_gfp", "size"), max_dias_atraso=("dias_atraso", "max"))
        .sort_values(["max_dias_atraso", "qtd_atraso", "empresa_gfp"], ascending=[False, False, True])
    )

    return [
        {
            "cliente": _text(row.get("empresa_gfp")),
            "demandas": int(float(row.get("qtd_atraso") or 0)),
            "dias": int(float(row.get("max_dias_atraso") or 0)),
        }
        for row in grouped.head(4).to_dict(orient="records")
    ]



def calculate_dashboard_state(
    *,
    resumo_records: list[dict[str, Any]],
    atualizacao_records: list[dict[str, Any]],
    atrasos_records: list[dict[str, Any]],
    cronograma_records: list[dict[str, Any]],
    filters: FilterState,
) -> dict[str, Any]:
    resumo = _resumo_lookup(resumo_records)
    filtered_df = apply_filters(cronograma_records, filters)

    # Conclusão de etapas
    if filters.is_all:
        conclusao = {
            category: resumo.get(indicator, 0.0)
            for category, indicator in CONCLUSION_INDICATORS.items()
        }
    else:
        conclusao = {}
        for category in CONCLUSION_ORDER:
            cat_df = filtered_df[filtered_df["categoria"].fillna("") == category]
            total = len(cat_df)
            finalizadas = int(cat_df["finalizada"].fillna(False).sum()) if total else 0
            conclusao[category] = (finalizadas / total * 100.0) if total else 0.0

    # Atualização
    if filters.is_all:
        atualizacao_rows = _format_stage_rows(_to_df(atualizacao_records), limit=3)
    else:
        atualizacao_rows = _build_filtered_updates(filtered_df)

    # Atrasos
    if filters.is_all:
        atraso_rows = _format_delay_rows(_to_df(atrasos_records), limit=4)
    else:
        atraso_rows = _build_filtered_delays(filtered_df)

    # Tempo médio
    if filters.is_all:
        tempo_medio = resumo.get("Tempo médio clientes (meses)", 0.0)
    else:
        unique_clients = filtered_df[["empresa_gfp", "meses_na_ize"]].drop_duplicates(subset=["empresa_gfp"])
        tempo_medio = float(unique_clients["meses_na_ize"].dropna().mean()) if not unique_clients.empty else 0.0

    # Demandas no cronograma
    if filters.is_all:
        demandas_media = resumo.get("Média por cliente (cronograma)", 0.0)
        clientes_menos_3 = int(round(resumo.get("Clientes abaixo do mínimo", 0.0)))
    else:
        cron_df = filtered_df[filtered_df["categoria"].fillna("") == "_cronograma"]
        if cron_df.empty:
            demandas_media = 0.0
            clientes_menos_3 = 0
        else:
            per_client = cron_df.groupby("empresa_gfp").size()
            demandas_media = float(per_client.mean()) if not per_client.empty else 0.0
            clientes_menos_3 = int((per_client < 3).sum()) if not per_client.empty else 0

    # Demandas finalizadas / pendentes
    if filters.is_all:
        finalizadas = int(round(resumo.get("Demandas finalizadas (total)", 0.0)))
        pendentes = int(round(resumo.get("Demandas pendentes", 0.0)))
        clientes_menos_3_final = int(round(resumo.get("Clientes abaixo do mínimo", 0.0)))
    else:
        work = filtered_df.copy()
        finalizadas = int(work["finalizada"].fillna(False).sum()) if not work.empty else 0
        pending_mask = (~work["finalizada"].fillna(False)) & (work["categoria"].fillna("") != "_outros") & (work["categoria"].fillna("") != "_cronograma")
        pendentes = int(pending_mask.sum()) if not work.empty else 0

        cron_df = work[work["categoria"].fillna("") == "_cronograma"]
        per_client = cron_df.groupby("empresa_gfp").size() if not cron_df.empty else pd.Series(dtype="int64")
        clientes_menos_3_final = int((per_client < 3).sum()) if not per_client.empty else 0

    total_gauge = finalizadas + pendentes
    conclusao_total = (finalizadas / total_gauge * 100.0) if total_gauge else 0.0

    return {
        "filters": {
            "consultor": filters.consultor,
            "time": filters.time,
            "cliente": filters.cliente,
        },
        "cards": {
            "conclusao": conclusao,
            "atualizacao": atualizacao_rows,
            "atrasos": atraso_rows,
            "tempo_medio": tempo_medio,
            "cronograma": {
                "media": demandas_media,
                "clientes_menos_3": clientes_menos_3,
            },
            "finalizadas": {
                "demandas": finalizadas,
                "pendentes": pendentes,
                "clientes_menos_3": clientes_menos_3_final,
                "conclusao_total": conclusao_total,
            },
        },
    }
