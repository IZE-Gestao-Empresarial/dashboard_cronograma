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
        return "0%"
    if abs(num - round(num)) < 0.05:
        return f"{int(round(num))}%"
    text = f"{num:.1f}".replace(".", ",")
    return f"{text}%"


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


def _polar_to_cartesian(cx: float, cy: float, r: float, angle_deg: float) -> tuple[float, float]:
    angle = math.radians(angle_deg)
    return (cx + r * math.cos(angle), cy + r * math.sin(angle))


def _arc_path(cx: float, cy: float, r: float, start_angle: float, end_angle: float) -> str:
    start = _polar_to_cartesian(cx, cy, r, start_angle)
    end = _polar_to_cartesian(cx, cy, r, end_angle)
    large_arc_flag = 1 if abs(end_angle - start_angle) > 180 else 0
    sweep_flag = 1
    return f"M {start[0]:.2f} {start[1]:.2f} A {r:.2f} {r:.2f} 0 {large_arc_flag} {sweep_flag} {end[0]:.2f} {end[1]:.2f}"


def _render_gauge(percentage: float | int | None) -> str:
    pct = _to_finite_number(percentage) or 0.0
    segments = 12
    filled = int(round((max(0.0, min(100.0, pct)) / 100.0) * segments))
    filled = max(0, min(segments, filled))
    gap = 4.0
    start = 180.0
    end = 360.0
    span = end - start
    seg_size = (span - gap * (segments - 1)) / segments

    paths = []
    angle = start
    for idx in range(segments):
        seg_start = angle
        seg_end = angle + seg_size
        css = "gauge-segment--filled" if idx < filled else "gauge-segment--empty"
        paths.append(
            f'<path d="{_arc_path(110, 118, 70, seg_start, seg_end)}" class="gauge-segment {css}" />'
        )
        angle = seg_end + gap

    return (
        f'<svg class="gauge-svg" viewBox="0 0 220 135" aria-hidden="true" focusable="false">'
        f'{"".join(paths)}'
        f'</svg>'
    )


def render_dashboard_html(state: dict, updated_at: str | None = None) -> str:
    cards = state.get("cards", {})
    conclusao = cards.get("conclusao", {})
    tempo_medio = cards.get("tempo_medio", 0.0)
    cronograma = cards.get("cronograma", {})
    finalizadas = cards.get("finalizadas", {})
    atualizacao_rows = cards.get("atualizacao", [])
    atraso_rows = cards.get("atrasos", [])

    html = f"""
    <div class="cronogramas-canvas">
      <section class="dash-card slot-top-left">
        <div class="dash-card-inner">
          <div class="card-title">% Conclusão de Etapas</div>
          <div class="conclusion-grid">{_render_conclusion_tiles(conclusao)}</div>
        </div>
      </section>

      <section class="dash-card slot-top-right">
        <div class="dash-card-inner">
          <div class="card-title">Atualização</div>
          <div class="table-card table-card--update">
            <div class="table-head table-head--2cols">
              <div>Cliente</div>
              <div class="table-cell--right">Última Etapa</div>
            </div>
            {_render_atualizacao_rows(atualizacao_rows)}
          </div>
        </div>
      </section>

      <section class="dash-card slot-left-middle">
        <div class="dash-card-inner dash-card-inner--centered">
          <div class="card-title">Tempo Médio Clientes</div>
          <div class="tempo-medio-wrap">
            <div class="tempo-medio-value">{_fmt_decimal(tempo_medio)}</div>
            <div class="tempo-medio-unit">meses</div>
          </div>
        </div>
      </section>

      <section class="dash-card slot-left-bottom">
        <div class="dash-card-inner">
          <div class="card-title">Demandas no Cronograma</div>
          <div class="cronograma-lines">
            <div class="info-line">
              <div class="info-line__icon info-line__icon--list"></div>
              <div class="info-line__value">{_fmt_decimal(cronograma.get('media', 0.0))}</div>
              <div class="info-line__label">Demandas (média)</div>
            </div>
            <div class="info-line">
              <div class="info-line__icon info-line__icon--alert"></div>
              <div class="info-line__value">{_fmt_int(cronograma.get('clientes_menos_3', 0))}</div>
              <div class="info-line__label">Clientes com menos que 3</div>
            </div>
          </div>
        </div>
      </section>

      <section class="dash-card slot-center">
        <div class="dash-card-inner">
          <div class="card-title">Demandas Finalizadas</div>
          <div class="finalizadas-body">
            <div class="gauge-wrap">
              {_render_gauge(finalizadas.get('conclusao_total', 0.0))}
              <div class="gauge-center">
                <div class="gauge-center__value">{_fmt_int(finalizadas.get('demandas', 0))}</div>
                <div class="gauge-center__label">Demandas</div>
              </div>
            </div>
            <div class="finalizadas-footer">
              <div class="mini-stat-card">
                <div class="mini-stat-card__label">Demandas pendentes</div>
                <div class="mini-stat-card__value">{_fmt_int(finalizadas.get('pendentes', 0))}</div>
              </div>
              <div class="mini-stat-card">
                <div class="mini-stat-card__label">Clientes com menos que 3</div>
                <div class="mini-stat-card__value">{_fmt_int(finalizadas.get('clientes_menos_3', 0))}</div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section class="dash-card slot-right-bottom">
        <div class="dash-card-inner">
          <div class="card-title">Demandas em Atraso</div>
          <div class="table-card table-card--delay">
            <div class="table-head table-head--3cols">
              <div>Cliente</div>
              <div>Demandas</div>
              <div class="table-cell--right">Atraso</div>
            </div>
            {_render_atraso_rows(atraso_rows)}
          </div>
        </div>
      </section>

      <div class="dashboard-updated-at">{escape(updated_at or '')}</div>
    </div>
    """
    return "".join(line.strip() for line in html.splitlines() if line.strip())
