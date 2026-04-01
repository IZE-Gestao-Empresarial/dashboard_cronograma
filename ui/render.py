from __future__ import annotations

from html import escape
from pathlib import Path
import math

import streamlit as st


_BASE_DIR = Path(__file__).resolve().parent.parent


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@st.cache_data(show_spinner=False)
def load_asset_text(rel_path: str) -> str:
    path = _BASE_DIR / rel_path
    if not path.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {path}")
    return _read_text(path)


def inject_global_css() -> None:
    css = load_asset_text("assets/dashboard.css") + "\n\n" + load_asset_text("assets/kiosk.css")
    st.markdown(f"<style>\n{css}\n</style>", unsafe_allow_html=True)


def _to_finite_number(value: float | int | None) -> float | None:
    if value is None:
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(num):
        return None
    return num


def _fmt_percent(value: float | int | None) -> str:
    num = _to_finite_number(value)
    if num is None:
        return '0<span class="conclusion-tile__percent">%</span>'
    return f'{int(round(num))}<span class="conclusion-tile__percent">%</span>'


def _fmt_decimal(value: float | int | None) -> str:
    num = _to_finite_number(value)
    if num is None:
        return "0"
    if abs(num - round(num)) < 0.05:
        return f"{int(round(num))}"
    return f"{num:.1f}".replace(".", ",")


def _fmt_int(value: float | int | None) -> str:
    num = _to_finite_number(value)
    if num is None:
        return "0"
    return f"{int(round(num)):,}".replace(",", ".")


def _render_conclusion_tiles(data: dict[str, float]) -> str:
    tiles = [
        ("Base", "tile--base"),
        ("Análises", "tile--analises"),
        ("Planejamento", "tile--planejamento"),
        ("Extras", "tile--extras"),
    ]
    html = []
    for label, css_class in tiles:
        html.append(
            f'<article class="conclusion-tile {css_class}">'
            f'<div class="conclusion-tile__label">{escape(label)}</div>'
            f'<div class="conclusion-tile__value">{_fmt_percent(data.get(label, 0.0))}</div>'
            f'</article>'
        )
    return "".join(html)


def _render_atualizacao_rows(rows: list[dict[str, str]]) -> str:
    if not rows:
        return '<div class="card-empty">Sem dados para os filtros selecionados.</div>'
    html = []
    for row in rows:
        html.append(
            f'<div class="table-row table-row--2cols">'
            f'<div class="table-cell table-cell--cliente">{escape(str(row.get("cliente") or "-"))}</div>'
            f'<div class="table-cell table-cell--accent table-cell--stage">{escape(str(row.get("etapa") or "-"))}</div>'
            f'</div>'
        )
    return "".join(html)


def _render_atraso_rows(rows: list[dict[str, str | int]]) -> str:
    if not rows:
        return '<div class="card-empty">Nenhuma demanda em atraso.</div>'
    html = []
    for row in rows:
        html.append(
            f'<div class="table-row table-row--3cols">'
            f'<div class="table-cell table-cell--cliente">{escape(str(row.get("cliente") or "-"))}</div>'
            f'<div class="table-cell table-cell--accent">{_fmt_int(row.get("demandas"))} em atraso</div>'
            f'<div class="table-cell table-cell--right">{_fmt_int(row.get("dias"))} dias</div>'
            f'</div>'
        )
    return "".join(html)


_GAUGE_PILL_D = (
    "M62.8002 0C71.6745 0 78.6088 7.66227 77.7257 16.4926"
    "L64.7257 146.493C63.9589 154.161 57.5065 160 49.8002 160"
    "H28.4077C20.7192 160 14.2755 154.187 13.4868 146.539"
    "L0.0805531 16.5387C-0.831684 7.69276 6.10858 0 15.0014 0"
    "L62.8002 0Z"
)


def _render_gauge(percentage: float | int | None) -> str:
    pct = max(0.0, min(100.0, _to_finite_number(percentage) or 0.0))
    segments = 13
    seg_len = 42.0
    r_inner = 75.0
    arc_start = 185.0
    arc_end = 355.0
    base_w, base_h = 78.0, 160.0
    filled_count = int(round((pct / 100.0) * segments))
    scale = seg_len / base_h
    step = (arc_end - arc_start) / float(segments)
    vb_w, vb_h = 240, 160
    cx, cy = 120, 123
    segs = []
    for i in range(segments):
        ang = arc_start + (i + 0.5) * step
        rad = math.radians(ang)
        x = cx + r_inner * math.cos(rad)
        y = cy + r_inner * math.sin(rad)
        color = "#f26419" if i < filled_count else "#e0ddd9"
        segs.append(
            f'<g transform="translate({x:.2f} {y:.2f}) rotate({ang + 90:.2f}) scale({scale:.4f}) translate({-base_w / 2:.2f} {-base_h:.2f})">'
            f'<path d="{_GAUGE_PILL_D}" fill="{color}"/>'
            f'</g>'
        )
    return f'<svg class="gauge-svg" viewBox="0 0 {vb_w} {vb_h}" aria-hidden="true" focusable="false">{"".join(segs)}</svg>'


def _render_card_corner_icon(toggle_id: str) -> str:
    svg = load_asset_text("assets/svg/card_corner_icon.svg").strip()
    return f'<label class="card-corner-link" for="{escape(toggle_id)}" aria-label="Abrir detalhamento">{svg}</label>'


def _render_detail_table(columns: list[str], rows: list[dict[str, str]]) -> str:
    head = ''.join(f'<th>{escape(str(col))}</th>' for col in columns)
    if not rows:
        body = f'<tr><td colspan="{max(1, len(columns))}" class="detail-empty-cell">Sem dados para os filtros selecionados.</td></tr>'
    else:
        body_rows = []
        for row in rows:
            cells = ''.join(f'<td>{escape(str(row.get(col, "-")))}</td>' for col in columns)
            body_rows.append(f'<tr>{cells}</tr>')
        body = ''.join(body_rows)
    return f'<div class="detail-table-wrap"><table class="detail-table"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def _render_detail_modal(detail: dict, toggle_id: str) -> str:
    title = escape(str(detail.get("title") or "Detalhamento"))
    download_href = str(detail.get("download_href") or "").strip()
    download_name = escape(str(detail.get("download_name") or "detalhamento.xlsx"))
    download_html = (
        f'<a class="detail-download-button" href="{escape(download_href, quote=True)}" download="{download_name}">↓&nbsp;&nbsp;Baixar</a>'
        if download_href else
        '<span class="detail-download-button detail-download-button--disabled">↓&nbsp;&nbsp;Baixar</span>'
    )
    return (
        f'<div class="detail-overlay">'
        f'<label class="detail-overlay__backdrop" for="{escape(toggle_id)}" aria-label="Fechar detalhamento"></label>'
        f'<div class="detail-page" role="dialog" aria-modal="true" aria-label="{title}">'
        f'<div class="detail-page__topbar">'
        f'<label class="detail-page__back" for="{escape(toggle_id)}">‹ Voltar para Dashboard</label>'
        f'<label class="detail-page__close" for="{escape(toggle_id)}" aria-label="Fechar">✕</label>'
        f'</div>'
        f'<div class="detail-page__header"><h1 class="detail-page__title">{title}</h1>{download_html}</div>'
        f'{_render_detail_table(detail.get("columns", []), detail.get("rows", []))}'
        f'</div></div>'
    )


def _wrap_card(content: str, detail: dict, key: str) -> str:
    toggle_id = f'detail-toggle-{key}'
    return (
        f'<input type="checkbox" class="detail-toggle" id="{toggle_id}">'
        f'{_render_card_corner_icon(toggle_id)}'
        f'{content}'
        f'{_render_detail_modal(detail, toggle_id)}'
    )


def render_dashboard_html(state: dict, updated_at: str | None = None) -> str:
    cards = state.get("cards", {})
    details = state.get("details", {})
    conclusao = cards.get("conclusao", {})
    tempo_medio = cards.get("tempo_medio", 0.0)
    cronograma = cards.get("cronograma", {})
    finalizadas = cards.get("finalizadas", {})
    atualizacao_rows = cards.get("atualizacao", [])
    atraso_rows = cards.get("atrasos", [])

    html = f"""
    <div class="cronogramas-canvas">
      <section class="dash-card slot-top-left">
        {_wrap_card(f'<div class="dash-card-inner"><div class="card-title">% Conclusão de Etapas</div><div class="conclusion-grid">{_render_conclusion_tiles(conclusao)}</div></div>', details.get('conclusao', {}), 'conclusao')}
      </section>

      <section class="dash-card slot-top-right">
        {_wrap_card(f'<div class="dash-card-inner"><div class="card-title">Atualização</div><div class="table-card table-card--update"><div class="table-head table-head--2cols"><div>Cliente</div><div class="table-cell--right">Última Etapa</div></div>{_render_atualizacao_rows(atualizacao_rows)}</div></div>', details.get('atualizacao', {}), 'atualizacao')}
      </section>

      <section class="dash-card slot-left-middle">
        {_wrap_card(f'<div class="dash-card-inner dash-card-inner--centered"><div class="card-title">Tempo Médio Clientes</div><div class="tempo-medio-wrap"><div class="tempo-medio-value">{_fmt_decimal(tempo_medio)}</div><div class="tempo-medio-unit">meses</div></div></div>', details.get('tempo_medio', {}), 'tempo_medio')}
      </section>

      <section class="dash-card slot-left-bottom">
        {_wrap_card(f'<div class="dash-card-inner"><div class="card-title">Demandas no Cronograma</div><div class="cronograma-lines"><div class="info-line"><div class="info-line__icon info-line__icon--list"></div><div class="info-line__value">{_fmt_decimal(cronograma.get("media", 0.0))}</div><div class="info-line__label">Demandas (média)</div></div><div class="info-line"><div class="info-line__icon info-line__icon--alert"></div><div class="info-line__value">{_fmt_int(cronograma.get("clientes_menos_3", 0))}</div><div class="info-line__label">Clientes com menos que 3</div></div></div></div>', details.get('cronograma', {}), 'cronograma')}
      </section>

      <section class="dash-card slot-center">
        {_wrap_card(f'<div class="dash-card-inner"><div class="card-title">Demandas Finalizadas</div><div class="finalizadas-body"><div class="gauge-wrap">{_render_gauge(finalizadas.get("conclusao_total", 0.0))}<div class="gauge-center"><div class="gauge-center__value">{_fmt_int(finalizadas.get("demandas", 0))}</div><div class="gauge-center__label">Demandas</div></div></div><div class="finalizadas-footer"><div class="mini-stat-card"><div class="mini-stat-card__label">Demandas pendentes</div><div class="mini-stat-card__value">{_fmt_int(finalizadas.get("pendentes", 0))}</div></div><div class="mini-stat-card"><div class="mini-stat-card__label">Clientes com menos que 3</div><div class="mini-stat-card__value">{_fmt_int(finalizadas.get("clientes_menos_3", 0))}</div></div></div></div></div>', details.get('finalizadas', {}), 'finalizadas')}
      </section>

      <section class="dash-card slot-right-bottom">
        {_wrap_card(f'<div class="dash-card-inner"><div class="card-title">Demandas em Atraso</div><div class="table-card table-card--delay"><div class="table-head table-head--3cols"><div>Cliente</div><div>Demandas</div><div class="table-cell--right">Atraso</div></div>{_render_atraso_rows(atraso_rows)}</div></div>', details.get('atrasos', {}), 'atrasos')}
      </section>

      <div class="dashboard-updated-at">{escape(updated_at or "")}</div>
    </div>
    """
    return ''.join(line.strip() for line in html.splitlines() if line.strip())
