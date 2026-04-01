# DashboardCronogramasGFP

Projeto do **Dashboard de Cronogramas GFP** em Streamlit, com layout responsivo baseado no protótipo **960x540** e leitura direta de uma planilha pública do Google Sheets.

## Estrutura
- `app.py` coordena carregamento, filtros e renderização
- `core/data.py` lê o Google Sheets, normaliza os dados e deriva os datasets internos
- `core/metrics.py` concentra os cálculos dos cards e detalhamentos
- `ui/render.py` gera o HTML final e injeta o CSS
- `assets/dashboard.css` e `assets/kiosk.css` contêm o layout visual

## Fonte de dados
O projeto usa um **ID de planilha fixo em `app.py`** e tenta carregar primeiro a aba principal configurada em `CRONOGRAMA_SHEET`.

Fallbacks atualmente configurados:
- `base_demanda`
- `df_preparado`
- `CRONOGRAMA_GF&P`

A partir dessa base do cronograma, o app deriva internamente:
- resumo
- atualização
- atrasos
- dataset consolidado para filtros

## Rodar localmente
```bash
pip install -r requirements.txt
streamlit run app.py
```

## Observações
- O projeto não depende de `secrets.toml` para o ID da planilha.
- Os datasets auxiliares são gerados a partir do cronograma carregado, sem necessidade de abas separadas.
