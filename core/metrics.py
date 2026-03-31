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

# Valores de status que indicam conclusão (comparados em lowercase)
DONE_STATUS_VALUES: frozenset[str] = frozenset({
    "feito", "done", "concluído", "concluido", "finalizado", "finalizada",
})

# Limite padrão de demandas finalizadas para alerta de clientes
DEFAULT_MIN_FINALIZADAS = 5

# Limite padrão de demandas no cronograma para alerta de clientes
DEFAULT_MIN_CRONOGRAMA = 3

# Valores de grupo_anterior que reclassificam a demanda para "Extras"
_GRUPO_ANTERIOR_EXTRAS: frozenset[str] = frozenset({
    "[sem movimentação registrada]",
    "Cronograma Atual",
})


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


def _is_done(status_value: Any) -> bool:
    """Retorna True quando o valor da coluna 'status' indica conclusão."""
    return _text(status_value).lower() in DONE_STATUS_VALUES


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


def resolve_categoria(grupo_nome: str, grupo_anterior: str, categoria_atual: str) -> str:
    """
    Pós-processamento de categoria: quando grupo_anterior for
    '[sem movimentação registrada]' ou 'Cronograma Atual', a demanda
    é reclassificada como 'Extras' independente do grupo_nome.

    Chamado em data.py após _infer_category para garantir que o dataframe
    do cronograma já chegue ao metrics.py com a categoria correta.
    """
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
        values = sorted(
            {_text(v) for v in df[column].dropna().tolist() if _text(v)},
            key=lambda x: x.casefold(),
        )
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
    """Formata linhas de atualização. Aceita data_atualizacao ou ultima_atualizacao_dt."""
    if df.empty:
        return []

    work = df.copy()

    # Suporta ambos os nomes de coluna de data
    date_col = None
    for candidate in ("data_atualizacao", "ultima_atualizacao_dt"):
        if candidate in work.columns:
            date_col = candidate
            break

    if date_col:
        work[date_col] = pd.to_datetime(work[date_col], errors="coerce")
        work = work.sort_values(date_col, ascending=False, na_position="last")

    company_col = "empresa_gfp_clean" if "empresa_gfp_clean" in work.columns else "empresa_gfp"
    stage_col = "ultima_etapa" if "ultima_etapa" in work.columns else "item_nome"

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
    cols = [col for col in [company_col, "qtd_atraso", "max_dias_atraso"] if col in work.columns]
    work = work[cols].copy()
    sort_cols = [c for c in ["max_dias_atraso", "qtd_atraso", company_col] if c in work.columns]
    asc = [False] * (len(sort_cols) - 1) + [True]
    work = work.sort_values(sort_cols, ascending=asc, na_position="last")
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
    if "ultima_atualizacao_dt" in work.columns:
        work = work.sort_values("ultima_atualizacao_dt", ascending=False, na_position="last")
    latest = work.groupby("empresa_gfp", as_index=False).first()
    if "ultima_atualizacao_dt" in latest.columns:
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
    # Apenas demandas COM previsao_dt registrada e NÃO concluídas
    delayed = filtered_df[
        filtered_df["em_atraso"].fillna(False)
        & filtered_df["previsao_dt"].notna()
        & ~filtered_df["status"].fillna("").apply(_is_done)
    ].copy()
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


def _build_tabela_clientes(filtered_df: pd.DataFrame) -> list[dict[str, Any]]:
    """
    Tabela consolidada por cliente com:
    - empresa_gfp, responsavel, area, meses_na_ize
    - total_demandas, finalizadas, pendentes (universo exclui _outros e _cronograma)
    - em_atraso, max_dias_atraso (só demandas com previsao_dt e não concluídas)
    - ultima_atualizacao: data da última modificação, independente da categoria
    - pct_conclusao: % de conclusão do cliente
    """
    if filtered_df.empty:
        return []

    exclude = {"_outros", "_cronograma"}
    work = filtered_df[~filtered_df["categoria"].fillna("").isin(exclude)].copy()

    if work.empty:
        return []

    work["_done"] = work["status"].fillna("").apply(_is_done)

    agg: dict[str, Any] = {
        "total_demandas": ("empresa_gfp", "size"),
        "finalizadas": ("_done", "sum"),
    }
    if "responsavel" in work.columns:
        agg["responsavel"] = ("responsavel", "first")
    if "area" in work.columns:
        agg["area"] = ("area", "first")
    if "meses_na_ize" in work.columns:
        agg["meses_na_ize"] = ("meses_na_ize", "first")

    base = work.groupby("empresa_gfp", as_index=False).agg(**agg)
    base["finalizadas"] = base["finalizadas"].astype(int)
    base["pendentes"] = base["total_demandas"] - base["finalizadas"]
    base["pct_conclusao"] = (base["finalizadas"] / base["total_demandas"] * 100.0).round(1)

    # Última atualização vem do df completo (independe de categoria)
    if "ultima_atualizacao_dt" in filtered_df.columns:
        last_upd = (
            filtered_df.groupby("empresa_gfp")["ultima_atualizacao_dt"]
            .max()
            .reset_index()
            .rename(columns={"ultima_atualizacao_dt": "ultima_atualizacao"})
        )
        base = base.merge(last_upd, on="empresa_gfp", how="left")
        base["ultima_atualizacao"] = pd.to_datetime(
            base["ultima_atualizacao"], errors="coerce"
        ).dt.strftime("%d/%m/%Y %H:%M")

    # Atrasos: só com prazo registrado e não concluídas
    if "em_atraso" in filtered_df.columns and "dias_atraso" in filtered_df.columns:
        delayed = filtered_df[
            filtered_df["previsao_dt"].notna()
            & ~filtered_df["status"].fillna("").apply(_is_done)
            & filtered_df["em_atraso"].fillna(False)
        ].copy()
        if not delayed.empty:
            atraso_agg = (
                delayed.groupby("empresa_gfp", as_index=False)
                .agg(em_atraso=("empresa_gfp", "size"), max_dias_atraso=("dias_atraso", "max"))
            )
            base = base.merge(atraso_agg, on="empresa_gfp", how="left")
        base["em_atraso"] = base.get("em_atraso", 0)
        base["max_dias_atraso"] = base.get("max_dias_atraso", 0)
        base["em_atraso"] = base["em_atraso"].fillna(0).astype(int)
        base["max_dias_atraso"] = base["max_dias_atraso"].fillna(0).astype(int)
    else:
        base["em_atraso"] = 0
        base["max_dias_atraso"] = 0

    base = base.sort_values("empresa_gfp", key=lambda s: s.str.casefold())
    return base.to_dict(orient="records")


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

    # ------------------------------------------------------------------
    # Conclusão de etapas
    # Regra: usa coluna 'status' (DONE_STATUS_VALUES), não 'finalizada'.
    # No modo is_all, lê os valores pré-calculados do resumo (já derivados
    # com a mesma lógica em data._build_resumo) para evitar reprocessar
    # o dataframe completo.
    # ------------------------------------------------------------------
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
            if total == 0:
                conclusao[category] = 0.0
                continue
            done = cat_df["status"].fillna("").apply(_is_done).sum()
            conclusao[category] = done / total * 100.0

    # ------------------------------------------------------------------
    # Atualização recente — independente da categoria
    # ------------------------------------------------------------------
    if filters.is_all:
        atualizacao_rows = _format_stage_rows(_to_df(atualizacao_records), limit=3)
    else:
        atualizacao_rows = _build_filtered_updates(filtered_df)

    # ------------------------------------------------------------------
    # Atrasos — apenas demandas COM previsao_dt e NÃO concluídas
    # ------------------------------------------------------------------
    if filters.is_all:
        atraso_rows = _format_delay_rows(_to_df(atrasos_records), limit=4)
    else:
        atraso_rows = _build_filtered_delays(filtered_df)

    # ------------------------------------------------------------------
    # Tempo médio — deduplicado por cliente
    # ------------------------------------------------------------------
    if filters.is_all:
        tempo_medio = resumo.get("Tempo médio clientes (meses)", 0.0)
    else:
        unique_clients = filtered_df[["empresa_gfp", "meses_na_ize"]].drop_duplicates(subset=["empresa_gfp"])
        tempo_medio = float(unique_clients["meses_na_ize"].dropna().mean()) if not unique_clients.empty else 0.0

    # ------------------------------------------------------------------
    # Demandas no cronograma — média por cliente por time
    # ------------------------------------------------------------------
    if filters.is_all:
        demandas_media = resumo.get("Média por cliente (cronograma)", 0.0)
        clientes_menos_3 = int(round(resumo.get("Clientes abaixo do mínimo", 0.0)))
    else:
        cron_df = filtered_df[filtered_df["categoria"].fillna("") == "_cronograma"]
        if cron_df.empty:
            demandas_media = 0.0
            clientes_menos_3 = 0
        else:
            group_cols = [c for c in ["area", "empresa_gfp"] if c in cron_df.columns]
            per_client = cron_df.groupby(group_cols).size()
            demandas_media = float(per_client.mean()) if not per_client.empty else 0.0
            clientes_menos_3 = int((per_client < DEFAULT_MIN_CRONOGRAMA).sum()) if not per_client.empty else 0

    # ------------------------------------------------------------------
    # Demandas finalizadas / pendentes
    # Regra: usa coluna 'status'. Universo exclui _outros e _cronograma.
    # clientes_menos_5: clientes com < DEFAULT_MIN_FINALIZADAS finalizadas.
    # ------------------------------------------------------------------
    if filters.is_all:
        finalizadas = int(round(resumo.get("Demandas finalizadas (total)", 0.0)))
        pendentes = int(round(resumo.get("Demandas pendentes", 0.0)))
        clientes_menos_3_final = int(round(resumo.get("Clientes abaixo do mínimo", 0.0)))
        clientes_menos_5 = int(round(resumo.get("Clientes com menos de 5 finalizadas", 0.0)))
    else:
        exclude = {"_outros", "_cronograma"}
        work = filtered_df[~filtered_df["categoria"].fillna("").isin(exclude)].copy()
        done_mask = work["status"].fillna("").apply(_is_done) if not work.empty else pd.Series(dtype=bool)
        finalizadas = int(done_mask.sum()) if not work.empty else 0
        pendentes = len(work) - finalizadas if not work.empty else 0

        cron_df2 = filtered_df[filtered_df["categoria"].fillna("") == "_cronograma"]
        if cron_df2.empty:
            clientes_menos_3_final = 0
        else:
            group_cols2 = [c for c in ["area", "empresa_gfp"] if c in cron_df2.columns]
            per_client2 = cron_df2.groupby(group_cols2).size()
            clientes_menos_3_final = int((per_client2 < DEFAULT_MIN_CRONOGRAMA).sum()) if not per_client2.empty else 0

        per_client_done = (
            work[done_mask].groupby("empresa_gfp").size()
            if not work.empty
            else pd.Series(dtype="int64")
        )
        clientes_menos_5 = int((per_client_done < DEFAULT_MIN_FINALIZADAS).sum()) if not per_client_done.empty else 0

    total_gauge = finalizadas + pendentes
    conclusao_total = (finalizadas / total_gauge * 100.0) if total_gauge else 0.0

    # ------------------------------------------------------------------
    # Tabela de clientes (para exibição e download)
    # ------------------------------------------------------------------
    tabela_clientes = _build_tabela_clientes(filtered_df)

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
                "clientes_menos_5": clientes_menos_5,
                "conclusao_total": conclusao_total,
            },
        },
        # Tabela detalhada por cliente (para exibição em tela e download)
        "tabela_clientes": tabela_clientes,
    }