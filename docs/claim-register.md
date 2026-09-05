# Claim register

What may and may not be said about this accelerator in front of a customer.

Read this before every delivery. The distinctions below are not stylistic — several came directly from the source study, which flags specific claims as unsupported by the evidence behind it.

## How to use this

Each boundary gives supported phrasing and phrasing to avoid. When a customer question falls outside these, say you will follow up rather than improvising a claim.

Any new presenter-facing material gets checked against this register before it ships.

---

## Boundary 1 — Product status

**Say:**

> "This is a reference architecture and accelerator built from validated genomics patterns and healthcare customer requirements."

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

> "The patterns here — SMB ingestion, object-storage staging, batch or HPC processing — are in production use across genomics customers."

**Do not say:**

- Any named customer attribution for *this* accelerator
- Any customer name carried over from earlier drafts of this material — those attributions are unverified and must not be used

Name a customer only when you have a cleared, current reference for the specific claim you are making.

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

## Boundary 5 — What is built

**Say:**

> "Here is what runs today, and here is what is specified but not yet built."

**Do not say:**

- Anything that implies a specified-only capability is working software
- "We can show you that" for something in the specified-only column

Check the coverage table in the [README](../README.md#coverage) before every delivery. It is the source of truth for this boundary, and it changes as capabilities land.

---

## Boundary 6 — Design assumptions

Several design elements are **proposed**, not confirmed. Present them as reasonable defaults you would validate with the customer, not as settled design:

- The eight-column VCF schema — the source material requires eight columns but does not enumerate them; the specs use the standard VCF core
- The hereditary-cancer demo scenario and its query set
- The specific visualization screens
- Delta partitioning and optimization strategy
- Query-performance targets and accelerator KPIs
- Full Microsoft Purview implementation, and the specific choice of Databricks, Fabric, Azure ML, or AI Foundry

**Say:** "This is the shape we would propose — we would validate it against your data volumes and workflows."

---

## Corrections carried from the source material

Two things in the original material do not survive contact with the platform documentation. If you have seen an earlier deck, these changed:

| Original claim | Reality |
|---|---|
| Azure Files → Storage Actions → Blob | Storage Actions operates on Blob and ADLS only. It cannot read a file share. The Files-to-Blob hop uses a Data Factory Copy activity; Storage Actions handles blob lifecycle after landing. |
| Event-driven file arrival | Event Grid raises no file-created event for Azure file shares. Arrival is detected by scheduled scan. |

The narrative shape is unchanged — landing zone, automated movement, object storage — so the story still works. The mechanism named on the slide does not.
