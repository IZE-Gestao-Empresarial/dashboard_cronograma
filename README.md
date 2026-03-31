# DashboardCronogramasGFP

Projeto do **Dashboard de Cronogramas GFP** montado sobre a mesma organização do Dashboard de Omissão, mas com layout próprio em **960x540** e escala proporcional para qualquer tela 16:9.

## Estrutura
- `app.py` coordena carregamento, filtros e renderização
- `core/data.py` faz a leitura do Google Sheets / Apps Script e normaliza as abas
- `core/metrics.py` concentra os cálculos dos cards
- `ui/render.py` gera o HTML final e injeta o CSS
- `assets/dashboard.css` contém todo o layout visual do dashboard

## Escala do layout
O canvas usa o protótipo **960x540** como base e mantém a proporção em qualquer resolução:
- largura do canvas = `min(100vw, 100vh * 16/9)`
- altura do canvas = `min(100vh, 100vw * 9/16)`

Assim, os espaçamentos, cards e filtros preservam a mesma malha visual do protótipo em Full HD e 4K.

## Abas esperadas no Sheets
Por padrão, o app lê estas abas:
- `Resumo`
- `Atualizacao_clientes`
- `Atrasos_por_cliente`
- `df_preparado`

Para o dataset filtrável do cronograma, o app tenta primeiro a aba configurada em `SHEETS_CRONOGRAMA_SHEET`. Se ela não existir ou vier vazia, ele tenta automaticamente:
- `CRONOGRAMA_GF&P`
- `base_demandas`

## Lógica dos cards
### Sem filtros (`Todos` / `Todos` / `Todos`)
- **% Conclusão de Etapas**: usa a aba `Resumo`
- **Atualização**: usa a aba `Atualizacao_clientes`
- **Demandas em Atraso**: usa a aba `Atrasos_por_cliente`
- **Tempo Médio Clientes**: usa a aba `Resumo`
- **Demandas no Cronograma**: usa a aba `Resumo`
- **Demandas Finalizadas**: usa a aba `Resumo`

### Com filtros ativos
Cruza as colunas do cronograma:
- `Time` → `area`
- `Consultor` → `responsavel`
- `Cliente` → `empresa_gfp`

A partir disso, recalcula os cards diretamente no dataset do cronograma preparado.

## Secrets
Exemplo mínimo:

```toml
SHEETS_WEBAPP_URL = "https://script.google.com/macros/s/SEU_WEBAPP/exec"
SHEETS_WEBAPP_TOKEN = "SEU_TOKEN"

SHEETS_RESUMO_SHEET = "Resumo"
SHEETS_ATUALIZACAO_SHEET = "Atualizacao_clientes"
SHEETS_ATRASOS_SHEET = "Atrasos_por_cliente"
SHEETS_CRONOGRAMA_SHEET = "df_preparado"
```

## Uso local opcional com Excel
Para rodar sem Apps Script, você pode apontar para arquivos `.xlsx` locais:

```toml
LOCAL_BASE_FILE = "base_indicadores.xlsx"
LOCAL_CRONOGRAMA_FILE = "CRONOGRAMA_GF&P.xlsx"
```

Nesse modo, o app usa:
- `LOCAL_BASE_FILE` para `Resumo`, `Atualizacao_clientes` e `Atrasos_por_cliente`
- `LOCAL_CRONOGRAMA_FILE` para a aba do cronograma

## Rodar localmente
```bash
pip install -r requirements.txt
streamlit run app.py
```
