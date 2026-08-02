# Group P&L BI Dashboard

A BI-grade Streamlit dashboard for the Group P&L consolidation workbook.

## Quick start

```bash
pip install -r requirements.txt
streamlit run app.py
```

Upload the `Group_PL_2026_Upload...xlsx` workbook in the sidebar.

## Architecture

```
app.py                         # Thin entrypoint (~60 lines)
.streamlit/config.toml         # Dark financial theme
streamlit_app/
  constants.py                 # All magic strings, colours, formatters
  data/
    loader.py                  # Cached sheet loading
    parsers.py                 # parse_pl_sheet, parse_ratios, parse_master,
                               #   parse_wip_margin, parse_tie_out
  components/
    kpi_cards.py               # Reusable KPI card row (st.metric + sparklines)
    filters.py                 # multiselect_with_all, sidebar filter bar
    charts.py                  # Plotly figure builders (trend, bar, waterfall, treemap)
  tabs/
    consolidated.py            # Consolidated Group P&L
    per_entity.py              # Per-entity comparison
    per_client.py              # Per-client analysis (from MASTER)
    margin_by_stream.py        # WIP Margin by Stream analysis
    data_health.py             # TIE-OUT CHECK reconciliation tool
```

## Tabs

| Tab | Key features |
|---|---|
| **Consolidated** | KPI cards w/ sparklines, metric trend, revenue area chart, margin % trend, P&L waterfall, styled P&L table |
| **Per-Entity** | Per-entity KPI cards, normalized IDR/% view, small-multiples grid, ranking table with ▲▼ arrows |
| **Per-Client** | Revenue concentration KPIs, treemap (Entity→Stream→Client), client search trend, new/churned clients |
| **Margin by Stream** | Stream KPI cards, stacked area/bar revenue, COGS and margin % if present |
| **Data Health** | Reconciliation delta table with red-flagged gaps, full pivot with cell-level conditional formatting |

## Data source quirks handled

- **USD block exclusion**: Parsing stops on `"in usd"` substring to avoid mixing IDR and USD tables
- **Depreciation disambiguation**: The two `Depreciation` rows (COGS vs OpEx) are relabeled using their surrounding section header
- **Ratio rows**: `Margin %`, `Growth %` etc. are parsed into a separate `ratios` DataFrame used for margin trend charts
- **MASTER sheet**: Header on row 2, data from row 3 — the only tidy/long-format sheet
