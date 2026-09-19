# Claim register

What may and may not be said about this accelerator in front of a customer.

Read this before every delivery. The distinctions below are not stylistic — several came directly from the source study, which flags specific claims as unsupported by the evidence behind it.

## How to use this

Each boundary gives supported phrasing and phrasing to avoid. When a customer question falls outside these, say you will follow up rather than improvising a claim.

Any new presenter-facing material gets checked against this register before it ships.
Run `python scripts/review_positioning.py --review-date YYYY-MM-DD
--check-report docs/positioning-review.json`; regenerate the report with
`--write-report` after reviewing a deliberate material change. The checked
[assumption register](assumption-register.json) keeps every proposal assumption
labelled until explicit reviewed confirmation is recorded.

---

## Boundary 1 — Released blueprint and product status

**Say:**

> "This is a reference architecture and accelerator built from validated genomics patterns and healthcare workload requirements."

> "It shows how the pieces fit together on Azure. It is a starting point you would adapt, not something you would deploy as-is."

**Do not say:**

- "Microsoft has a genomics accelerator" — implies a released offering
- "This is a Microsoft blueprint"
- "This is generally available" / "supported" / "productized"

**If asked directly whether this is a Microsoft product:** No. It is an accelerator assembled from patterns that are individually validated. There is no support commitment attached to it.

---

## Boundary 2 — Compliance

**Say:**

> "These are configurable governance building blocks — access tiers, managed identity, classification, lineage, audit."

> "Whether a deployment meets your regulatory obligations depends on your configuration, jurisdiction, policies, and operating procedures."

**Do not say:**

- "This makes your genomic data compliant"
- "This is HIPAA compliant" / "GDPR compliant" / any named-regulation compliance claim about the accelerator
- "This handles the compliance side for you"

Compliance is a property of a customer's whole operating environment, not of an architecture diagram.

---

## Boundary 3 — Customer references

**Say:**

> "This architecture brings together established Azure patterns for genomics ingestion, object-storage staging, batch or HPC processing, and analytics."

> "We can discuss a customer example only when the evidence and approval are current for the exact statement."

**Do not say:**

- "These patterns are in production use across genomics customers"
- "Customers use this accelerator in production" or any similarly broad, unsupported deployment claim
- Any named customer attribution for *this* accelerator
- Any customer name carried over from earlier drafts of this material — those attributions are unverified and must not be used

Do not infer customer deployment from general architecture patterns. Name a customer or describe customer production use only when you have a cleared, current reference for the specific claim you are making.

---

## Boundary 4 — Clinical use

**Say:**

> "The analytics surface supports research interpretation and cohort exploration."

> "AI-assisted exploration is a research aid — it helps you author queries and explore cohorts."

**Do not say:**

- "This supports clinical decision-making"
- "The AI interprets variants" / "diagnoses" / "determines pathogenicity"
- Anything positioning assisted output as a clinical determination

Assisted output is labelled exploratory in the product surface, and should be described the same way out loud.

---

## Presenter review checklist

Complete this review before presenter-facing material ships or is delivered:

- **Scope:** List every reviewed presenter-facing file, including slides, speaker notes, scripts, demos, and handouts.
- **Attribution:** For every customer name, customer-use statement, or production-use statement, record the supporting evidence and confirm that approval is current for the exact wording. Remove or qualify the statement when either is missing.
- **Coverage and assumptions:** Check every demonstrated or described capability against the [capability coverage table](coverage.md). Distinguish what runs today from what is specified only, and label proposed defaults as assumptions to validate. This includes the VCF schema, demo scenario and queries, visualizations, Delta strategy, performance targets or KPIs, Purview scope, and analytics-service choices.
- **Contextual searches:** Search the reviewed files for customer names and terms such as `customer`, `production`, `deployed`, `blueprint`, `generally available`, `supported`, `compliant`, `HIPAA`, `GDPR`, `clinical`, `diagnoses`, and `pathogenicity`. Inspect each match in context and record its disposition rather than treating a zero-match search as sufficient review.
- **Review record:** Record the reviewed files, reviewer, review date, result (`pass` or `changes required`), evidence or approval checked, coverage or assumptions checked, search terms used, and how every flagged match was resolved.

---

## Corrections carried from the source material

Two things in the original material do not survive contact with the platform documentation. If you have seen an earlier deck, these changed:

| Original claim | Reality |
|---|---|
| Azure Files → Storage Actions → Blob | Storage Actions operates on Blob and ADLS only. It cannot read a file share. The Files-to-Blob hop uses a Data Factory Copy activity; Storage Actions handles blob lifecycle after landing. |
| Event-driven file arrival | Event Grid raises no file-created event for Azure file shares. Arrival is detected by scheduled scan. |

The narrative shape is unchanged — landing zone, automated movement, object storage — so the story still works. The mechanism named on the slide does not.
