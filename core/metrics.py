from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any
import math

import pandas as pd


ALL_OPTION = "Todos"
CONCLUSION_ORDER = ["Base", "Análises", "Planejamento", "Extras"]
CONCLUSION_INDICATORS = {
    "Base": "% conclusão — Base",
    "Análises": "% conclusão — Análises",
    "Planejamento": "% conclusão — Planejamento",
    "Extras": "% conclusão — Extras",
}
DONE_STATUS_VALUES: frozenset[str] = frozenset({
    "feito", "done", "concluído", "concluido", "finalizado", "finalizada",
})
DEFAULT_MIN_FINALIZADAS = 5
DEFAULT_MIN_CRONOGRAMA = 3
EXCLUDED_FINAL_FILTER_CATEGORIES: frozenset[str] = frozenset({"_outros", "_cronograma"})
_GRUPO_ANTERIOR_EXTRAS: frozenset[str] = frozenset({
    "[sem movimentação registrada]",
    "Cronograma Atual",
})
DETAIL_CARD_TITLES = {
    "conclusao": "% Conclusão de Etapas",
    "atualizacao": "Atualização",
    "tempo_medio": "Tempo Médio Clientes",
    "cronograma": "Demandas no Cronograma",
    "finalizadas": "Demandas Finalizadas",
    "atrasos": "Demandas em Atraso",
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


def _strip_bracket_suffix(value: Any) -> str:
    text = _text(value)
    if not text:
        return ""
    return re.sub(r"\s*\[[^\]]*\]", "", text).strip()


def _is_done(status_value: Any) -> bool:
    return _text(status_value).lower() in DONE_STATUS_VALUES


def _normalize_resumo_value(value: Any) -> float:
    if isinstance(value, (int, float)):
        num = float(value)
        return num if math.isfinite(num) else 0.0
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
        num = float(text)
        return num if math.isfinite(num) else 0.0
    except ValueError:
        return 0.0


def resolve_categoria(grupo_nome: str, grupo_anterior: str, categoria_atual: str) -> str:
    if _text(grupo_anterior) in _GRUPO_ANTERIOR_EXTRAS:
        return "Extras"
    return categoria_atual


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
    if filters.consultor != ALL_OPTION and "responsavel" in df.columns:
        df = df[df["responsavel"].fillna("").astype(str) == filters.consultor]
    if filters.time != ALL_OPTION and "area" in df.columns:
        df = df[df["area"].fillna("").astype(str) == filters.time]
    if filters.cliente != ALL_OPTION and "empresa_gfp" in df.columns:
        df = df[df["empresa_gfp"].fillna("").astype(str) == filters.cliente]
    return df.reset_index(drop=True)


def _safe_int(value: Any) -> int:
    try:
        num = float(value)
        return int(round(num)) if math.isfinite(num) else 0
    except Exception:
        return 0


def _fmt_decimal(value: Any) -> str:
    num = _normalize_resumo_value(value)
    if abs(num - round(num)) < 0.05:
        return f"{int(round(num))}"
    return f"{num:.1f}".replace(".", ",")


def _fmt_pct(value: Any) -> str:
    return f"{_safe_int(value)}%"


def _fmt_date(value: Any, with_time: bool = False) -> str:
    dt = pd.to_datetime(value, errors="coerce")
    if pd.isna(dt):
        return "-"
    return dt.strftime("%d/%m/%Y %H:%M") if with_time else dt.strftime("%d/%m/%Y")


def _client_latest_demands(filtered_df: pd.DataFrame, limit: int = 3) -> list[dict[str, Any]]:
    if filtered_df.empty:
        return []
    work = filtered_df.copy()
    if "ultima_atualizacao_dt" in work.columns:
        work = work.sort_values("ultima_atualizacao_dt", ascending=False, na_position="last")
    latest = work.groupby("empresa_gfp", as_index=False).first() if "empresa_gfp" in work.columns else work
    if "ultima_atualizacao_dt" in latest.columns:
        latest = latest.sort_values("ultima_atualizacao_dt", ascending=False, na_position="last")
    return [
        {
            "cliente": _strip_bracket_suffix(row.get("empresa_gfp")),
            "etapa": _text(row.get("item_nome") or row.get("ultima_etapa") or row.get("grupo_nome")),
        }
        for row in latest.head(limit).to_dict(orient="records")
    ]


def _delay_preview(filtered_df: pd.DataFrame, limit: int = 4) -> list[dict[str, Any]]:
    delayed = _slice_atrasos(filtered_df)
    if delayed.empty:
        return []
    grouped = (
        delayed.groupby("empresa_gfp", as_index=False)
        .agg(qtd_atraso=("empresa_gfp", "size"), max_dias_atraso=("dias_atraso", "max"))
        .sort_values(["max_dias_atraso", "qtd_atraso", "empresa_gfp"], ascending=[False, False, True])
    )
    return [
        {
            "cliente": _strip_bracket_suffix(row.get("empresa_gfp")),
            "demandas": _safe_int(row.get("qtd_atraso")),
            "dias": _safe_int(row.get("max_dias_atraso")),
        }
        for row in grouped.head(limit).to_dict(orient="records")
    ]


def _slice_categoria(df: pd.DataFrame, categoria: str) -> pd.DataFrame:
    if df.empty or "categoria" not in df.columns:
        return pd.DataFrame(columns=df.columns)
    return df[df["categoria"].fillna("") == categoria].copy()


def _slice_tempo_medio(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=df.columns)
    work = df.copy()
    sort_cols = [c for c in ["empresa_gfp", "ultima_atualizacao_dt"] if c in work.columns]
    if sort_cols:
        work = work.sort_values(sort_cols, ascending=[True, False] if len(sort_cols) == 2 else [True], na_position="last")
    if "empresa_gfp" in work.columns:
        work = work.drop_duplicates(subset=["empresa_gfp"], keep="first")
    return work.reset_index(drop=True)


def _slice_cronograma(df: pd.DataFrame) -> pd.DataFrame:
    return _slice_categoria(df, "_cronograma")


def _slice_finalizadas(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=df.columns)
    work = df[~df["categoria"].fillna("").isin(EXCLUDED_FINAL_FILTER_CATEGORIES)].copy()
    return work[work["status"].fillna("").apply(_is_done)].reset_index(drop=True)


def _slice_pendentes(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=df.columns)
    work = df[~df["categoria"].fillna("").isin(EXCLUDED_FINAL_FILTER_CATEGORIES)].copy()
    return work[~work["status"].fillna("").apply(_is_done)].reset_index(drop=True)


def _slice_atualizacao(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=df.columns)
    work = df.copy()
    if "ultima_atualizacao_dt" in work.columns:
        work = work.sort_values("ultima_atualizacao_dt", ascending=False, na_position="last")
    return work.reset_index(drop=True)


def _slice_atrasos(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=df.columns)
    work = df.copy()
    if "status" not in work.columns:
        work["status"] = ""
    mask = (
        work.get("em_atraso", pd.Series(index=work.index, dtype="bool")).fillna(False)
        & work.get("previsao_dt", pd.Series(index=work.index, dtype="datetime64[ns]")).notna()
        & ~work["status"].fillna("").apply(_is_done)
    )
    delayed = work[mask].copy()
    if "dias_atraso" in delayed.columns:
        delayed = delayed.sort_values(["dias_atraso", "empresa_gfp"], ascending=[False, True], na_position="last")
    return delayed.reset_index(drop=True)


def _build_tabela_clientes(filtered_df: pd.DataFrame) -> list[dict[str, Any]]:
    if filtered_df.empty:
        return []
    universe = filtered_df[~filtered_df["categoria"].fillna("").isin(EXCLUDED_FINAL_FILTER_CATEGORIES)].copy()
    universe["done"] = universe["status"].fillna("").apply(_is_done)
    grouped = universe.groupby("empresa_gfp", as_index=False).agg(
        responsavel=("responsavel", "first"),
        area=("area", "first"),
        meses_na_ize=("meses_na_ize", "first"),
        total_demandas=("empresa_gfp", "size"),
        finalizadas=("done", "sum"),
    ) if not universe.empty else pd.DataFrame(columns=["empresa_gfp", "responsavel", "area", "meses_na_ize", "total_demandas", "finalizadas"])
    if grouped.empty:
        return []
    grouped["finalizadas"] = grouped["finalizadas"].astype(int)
    grouped["pendentes"] = grouped["total_demandas"] - grouped["finalizadas"]
    grouped["pct_conclusao"] = (grouped["finalizadas"] / grouped["total_demandas"] * 100.0).fillna(0).round(1)
    if "ultima_atualizacao_dt" in filtered_df.columns:
        last_upd = filtered_df.groupby("empresa_gfp", as_index=False)["ultima_atualizacao_dt"].max()
        grouped = grouped.merge(last_upd, on="empresa_gfp", how="left")
    delayed = _slice_atrasos(filtered_df)
    if not delayed.empty:
        atraso_agg = delayed.groupby("empresa_gfp", as_index=False).agg(
            qtd_atraso=("empresa_gfp", "size"),
            max_dias_atraso=("dias_atraso", "max"),
        )
        grouped = grouped.merge(atraso_agg, on="empresa_gfp", how="left")
    if "qtd_atraso" not in grouped.columns:
        grouped["qtd_atraso"] = 0
    else:
        grouped["qtd_atraso"] = pd.to_numeric(grouped["qtd_atraso"], errors="coerce").fillna(0).astype(int)
    if "max_dias_atraso" not in grouped.columns:
        grouped["max_dias_atraso"] = 0
    else:
        grouped["max_dias_atraso"] = pd.to_numeric(grouped["max_dias_atraso"], errors="coerce").fillna(0).astype(int)
    grouped = grouped.sort_values("empresa_gfp", key=lambda s: s.fillna("").astype(str).str.casefold())
    return grouped.to_dict(orient="records")


def _build_detail_views(filtered_df: pd.DataFrame) -> dict[str, dict[str, Any]]:
    details: dict[str, dict[str, Any]] = {}

    conclusao = filtered_df[filtered_df["categoria"].fillna("").isin(CONCLUSION_ORDER)].copy() if not filtered_df.empty and "categoria" in filtered_df.columns else pd.DataFrame()
    if conclusao.empty:
        conclusao_rows = []
    else:
        category_order = {name: idx for idx, name in enumerate(CONCLUSION_ORDER)}
        conclusao["__cat_order"] = conclusao["categoria"].map(category_order).fillna(999).astype(int)
        conclusao["__empresa_sort"] = conclusao.get("empresa_gfp", "").fillna("").astype(str).str.casefold() if "empresa_gfp" in conclusao.columns else ""
        sort_cols = ["__cat_order"]
        ascending = [True]
        if "empresa_gfp" in conclusao.columns:
            sort_cols.append("__empresa_sort")
            ascending.append(True)
        if "ultima_atualizacao_dt" in conclusao.columns:
            sort_cols.append("ultima_atualizacao_dt")
            ascending.append(False)
        conclusao = conclusao.sort_values(sort_cols, ascending=ascending, na_position="last")
        conclusao_rows = [
            {
                "Categoria": _text(row.get("categoria")) or "-",
                "Cliente": _text(row.get("empresa_gfp")) or "-",
                "Demanda": _text(row.get("item_nome")) or "-",
                "Grupo atual": _text(row.get("grupo_nome")) or "-",
                "Status": _text(row.get("status")) or "-",
                "Previsão": _fmt_date(row.get("previsao_dt")),
                "Atualizado em": _fmt_date(row.get("ultima_atualizacao_dt"), with_time=True),
                "Responsável": _text(row.get("responsavel")) or "-",
                "Time": _text(row.get("area")) or "-",
            }
            for row in conclusao.to_dict(orient="records")
        ]
    details["conclusao"] = {
        "title": DETAIL_CARD_TITLES["conclusao"],
        "download_name": "detalhamento_conclusao_etapas.xlsx",
        "columns": ["Categoria", "Cliente", "Demanda", "Grupo atual", "Status", "Previsão", "Atualizado em", "Responsável", "Time"],
        "rows": conclusao_rows,
    }

    atualizacao = _slice_atualizacao(filtered_df)
    _atualizacao_rows = [
        {
            "Cliente": _text(row.get("empresa_gfp")) or "-",
            "Demanda": _text(row.get("item_nome")) or "-",
            "Grupo atual": _text(row.get("grupo_nome")) or "-",
            "Status": _text(row.get("status")) or "-",
            "Atualizado em": _fmt_date(row.get("ultima_atualizacao_dt"), with_time=True),
            "Responsável": _text(row.get("responsavel")) or "-",
            "Time": _text(row.get("area")) or "-",
        }
        for row in atualizacao.to_dict(orient="records")
    ]
    details["atualizacao"] = {
        "title": DETAIL_CARD_TITLES["atualizacao"],
        "download_name": "detalhamento_atualizacao.xlsx",
        "columns": ["Cliente", "Demanda", "Grupo atual", "Status", "Atualizado em", "Responsável", "Time"],
        "rows": _atualizacao_rows[:300],
        "download_rows": _atualizacao_rows,
    }

    tempo = _slice_tempo_medio(filtered_df)
    demand_count = filtered_df.groupby("empresa_gfp").size().to_dict() if not filtered_df.empty else {}
    details["tempo_medio"] = {
        "title": DETAIL_CARD_TITLES["tempo_medio"],
        "download_name": "detalhamento_tempo_medio.xlsx",
        "columns": ["Cliente", "Tempo na IZE (meses)", "Demandas", "Responsável", "Time"],
        "rows": [
            {
                "Cliente": _text(row.get("empresa_gfp")) or "-",
                "Tempo na IZE (meses)": _fmt_decimal(row.get("meses_na_ize")),
                "Demandas": _safe_int(demand_count.get(row.get("empresa_gfp"), 0)),
                "Responsável": _text(row.get("responsavel")) or "-",
                "Time": _text(row.get("area")) or "-",
            }
            for row in tempo.sort_values([c for c in ["meses_na_ize", "empresa_gfp"] if c in tempo.columns], ascending=[False, True] if {"meses_na_ize", "empresa_gfp"}.issubset(set(tempo.columns)) else True, na_position="last").to_dict(orient="records")
        ],
    }

    cron = _slice_cronograma(filtered_df)
    if cron.empty:
        cron_rows = []
    else:
        cron_rows_df = cron.groupby("empresa_gfp", as_index=False).agg(
            Time=("area", "first"),
            Responsável=("responsavel", "first"),
            Demandas=("empresa_gfp", "size"),
            Última_atualização=("ultima_atualizacao_dt", "max"),
            Próxima_entrega=("previsao_dt", "min"),
        )
        cron_rows_df["Situação"] = cron_rows_df["Demandas"].apply(lambda n: "Abaixo do mínimo" if n < DEFAULT_MIN_CRONOGRAMA else "Dentro do esperado")
        cron_rows_df = cron_rows_df.sort_values(["Demandas", "empresa_gfp"], ascending=[True, True], na_position="last")
        cron_rows = [
            {
                "Cliente": _text(row.get("empresa_gfp")) or "-",
                "Demandas no cronograma": _safe_int(row.get("Demandas")),
                "Situação": _text(row.get("Situação")) or "-",
                "Próxima entrega": _fmt_date(row.get("Próxima_entrega")),
                "Última atualização": _fmt_date(row.get("Última_atualização"), with_time=True),
                "Responsável": _text(row.get("Responsável")) or "-",
                "Time": _text(row.get("Time")) or "-",
            }
            for row in cron_rows_df.to_dict(orient="records")
        ]
    details["cronograma"] = {
        "title": DETAIL_CARD_TITLES["cronograma"],
        "download_name": "detalhamento_cronograma.xlsx",
        "columns": ["Cliente", "Demandas no cronograma", "Situação", "Próxima entrega", "Última atualização", "Responsável", "Time"],
        "rows": cron_rows,
    }

    tabela_clientes = _build_tabela_clientes(filtered_df)
    final_rows = [
        {
            "Cliente": _text(row.get("empresa_gfp")) or "-",
            "Finalizadas": _safe_int(row.get("finalizadas")),
            "Pendentes": _safe_int(row.get("pendentes")),
            "% Conclusão": _fmt_pct(row.get("pct_conclusao")),
            "Responsável": _text(row.get("responsavel")) or "-",
            "Time": _text(row.get("area")) or "-",
            "Última atualização": _fmt_date(row.get("ultima_atualizacao_dt"), with_time=True),
        }
        for row in tabela_clientes
    ]
    details["finalizadas"] = {
        "title": DETAIL_CARD_TITLES["finalizadas"],
        "download_name": "detalhamento_finalizadas.xlsx",
        "columns": ["Cliente", "Finalizadas", "Pendentes", "% Conclusão", "Responsável", "Time", "Última atualização"],
        "rows": final_rows,
    }

    atrasos = _slice_atrasos(filtered_df)
    details["atrasos"] = {
        "title": DETAIL_CARD_TITLES["atrasos"],
        "download_name": "detalhamento_atrasos.xlsx",
        "columns": ["Cliente", "Demanda", "Grupo atual", "Previsão", "Dias em atraso", "Responsável", "Time", "Status"],
        "rows": [
            {
                "Cliente": _text(row.get("empresa_gfp")) or "-",
                "Demanda": _text(row.get("item_nome")) or "-",
                "Grupo atual": _text(row.get("grupo_nome")) or "-",
                "Previsão": _fmt_date(row.get("previsao_dt")),
                "Dias em atraso": _safe_int(row.get("dias_atraso")),
                "Responsável": _text(row.get("responsavel")) or "-",
                "Time": _text(row.get("area")) or "-",
                "Status": _text(row.get("status")) or "-",
            }
            for row in atrasos.to_dict(orient="records")
        ],
    }

    return details


def calculate_dashboard_state(
    *,
    resumo_records: list[dict[str, Any]],
    atualizacao_records: list[dict[str, Any]],
    atrasos_records: list[dict[str, Any]],
    cronograma_records: list[dict[str, Any]],
    filters: FilterState,
) -> dict[str, Any]:
    filtered_df = apply_filters(cronograma_records, filters)

    conclusao: dict[str, float] = {}
    for categoria in CONCLUSION_ORDER:
        cat_df = _slice_categoria(filtered_df, categoria)
        total = len(cat_df)
        finalizadas = int(cat_df["status"].fillna("").apply(_is_done).sum()) if total else 0
        conclusao[categoria] = (finalizadas / total * 100.0) if total else 0.0

    atualizacao_rows = _client_latest_demands(filtered_df, limit=3)
    atraso_rows = _delay_preview(filtered_df, limit=4)

    tempo_df = _slice_tempo_medio(filtered_df)
    tempo_medio = float(tempo_df["meses_na_ize"].dropna().mean()) if not tempo_df.empty and "meses_na_ize" in tempo_df.columns else 0.0

    cron_df = _slice_cronograma(filtered_df)
    if cron_df.empty:
        demandas_media = 0.0
        clientes_menos_3 = 0
    else:
        per_client = cron_df.groupby("empresa_gfp").size()
        demandas_media = float(per_client.mean()) if not per_client.empty else 0.0
        clientes_menos_3 = int((per_client < DEFAULT_MIN_CRONOGRAMA).sum()) if not per_client.empty else 0

    universe = filtered_df[~filtered_df["categoria"].fillna("").isin(EXCLUDED_FINAL_FILTER_CATEGORIES)].copy()
    done_mask = universe["status"].fillna("").apply(_is_done) if not universe.empty else pd.Series(dtype=bool)
    finalizadas = int(done_mask.sum()) if not universe.empty else 0
    pendentes = int((~done_mask).sum()) if not universe.empty else 0
    per_client_done = universe[done_mask].groupby("empresa_gfp").size() if not universe.empty and done_mask.any() else pd.Series(dtype="int64")
    clientes_menos_5 = int((per_client_done < DEFAULT_MIN_FINALIZADAS).sum()) if not per_client_done.empty else 0
    total_gauge = finalizadas + pendentes
    conclusao_total = (finalizadas / total_gauge * 100.0) if total_gauge else 0.0

    tabela_clientes = _build_tabela_clientes(filtered_df)
    details = _build_detail_views(filtered_df)

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
                "clientes_menos_3": clientes_menos_3,
                "clientes_menos_5": clientes_menos_5,
                "conclusao_total": conclusao_total,
            },
        },
        "details": details,
        "tabela_clientes": tabela_clientes,
    }
