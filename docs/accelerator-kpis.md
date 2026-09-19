# Accelerator KPIs

Task 12.2 is demonstrated by a **local synthetic measurement harness**. It is
not Azure production telemetry, a cloud pipeline run, or a cost estimate.
`scripts/accelerator_kpis.py` creates local SQLite event, cost-ledger, Bronze
variant-store, and metadata-store files, executes a narrowly scoped synthetic
pipeline history, runs a governed query, and calculates all values from the
persisted records.

Run it from the repository root:

```powershell
python scripts\accelerator_kpis.py --state-root <local-state-root>
```

The JSON contains these measured metrics:

| KPI | Calculation from recorded data |
|---|---|
| Pipeline success rate | Successful terminal `pipeline_finished` events ÷ all successful or failed terminal events |
| Arrival-to-queryable duration | Mean `queryable` timestamp minus `arrival` timestamp for each recorded run |
| Query response time | Mean recorded `query_finished` timestamp minus `query_started` timestamp around an actual governed query |
| Records linked to source files | Bronze rows with a non-empty `source_file_uri` ÷ all Bronze rows |
| Reprocessing time | Mean successful reprocessing `pipeline_finished` timestamp minus its recorded `pipeline_started` timestamp |
| Cost per sample | Sum of cost-ledger amounts ÷ distinct samples in that ledger |

The harness uses synthetic identifiers and metadata only. Its charges are
explicit local synthetic ledger entries, not Azure prices, forecasts, or a
claim about production cost. The event table, cost ledger, and generated
Bronze store are the sources of every numerator, denominator, and duration;
missing source data raises an error rather than returning an estimate.

An Azure deployment must replace the local harness with production telemetry
that records the same event boundaries and actual billed costs before any
production KPI claim is made.
