## Purpose

Covers what a Microsoft solution engineer does with this repository end to end — validate that their subscription can host it, provision it, deliver the demo, reset, and tear down — including the claim boundaries that govern what they say while presenting.

## ADDED Requirements

### Requirement: Prerequisites are declared and machine-checkable

The repository SHALL declare every prerequisite for provisioning: required Azure subscription type, the roles the deploying principal needs, the compute and storage quota the demo consumes, the regions where every component is available, and the local tooling with minimum versions. A preflight check SHALL verify these and report which are unmet.

#### Scenario: Engineer runs preflight on an unprepared subscription

- **WHEN** an engineer runs the preflight check before provisioning
- **THEN** it reports each unmet prerequisite by name, with the value found and the value required

#### Scenario: Preflight passes

- **WHEN** every prerequisite is satisfied
- **THEN** the preflight check reports readiness and names the region it validated against

#### Scenario: Component unavailable in the chosen region

- **WHEN** the selected region does not offer a required component
- **THEN** preflight fails naming the component and the regions where it is available

### Requirement: Preflight precedes provisioning

Provisioning SHALL refuse to start when preflight has not passed, so that an engineer does not discover a missing quota or role partway through a partially built environment.

#### Scenario: Provisioning attempted with unmet quota

- **WHEN** provisioning is started while a required quota is unmet
- **THEN** it refuses to start and reports the failing check
- **AND** no resource is created

### Requirement: No environment-specific values in the repository

The repository SHALL contain no tenant identifier, subscription identifier, resource name, hostname, or principal that is specific to the original author's environment. Every such value SHALL be a declared parameter with a documented default or a required input.

#### Scenario: Another engineer deploys unmodified

- **WHEN** an engineer clones the repository and supplies only the documented required inputs
- **THEN** provisioning completes without editing any tracked file

#### Scenario: Scanning for leaked identifiers

- **WHEN** the repository is scanned for subscription identifiers, tenant identifiers, and author-specific resource names
- **THEN** no match is found outside documentation examples that are marked as examples

### Requirement: Provisioning is repeatable and idempotent

Provisioning SHALL be executable from a single documented entry point, SHALL be safe to re-run after a partial failure, and SHALL state its expected duration. Re-running against a complete environment SHALL NOT duplicate resources. The entry point SHALL report whether there are effective desired-state changes after normalizing documented ARM what-if noise from server-defaulted, read-only, or runtime-resolved properties. Raw what-if output and every normalization rule SHALL remain inspectable; an unrecognized create, delete, modify, or unsupported result SHALL prevent a no-change report.

#### Scenario: Provisioning is re-run after a failure

- **WHEN** provisioning fails partway and is re-run
- **THEN** it completes the remaining work without duplicating what already exists

#### Scenario: Provisioning is re-run against a complete environment

- **WHEN** provisioning is re-run against an environment that is already complete
- **THEN** it reports no effective changes after applying the documented normalization rules
- **AND** it creates no additional resources

#### Scenario: What-if returns an unrecognized difference

- **WHEN** ARM what-if returns a difference that is not covered by a documented normalization rule
- **THEN** provisioning reports the difference as a pending change
- **AND** it does not describe the environment as unchanged

### Requirement: Cost is stated before provisioning

The repository SHALL state the estimated cost of one delivery, the cost of leaving the environment running while idle, and which resources dominate each figure. The estimate SHALL name the date and region it was produced for.

#### Scenario: Engineer evaluates cost before committing

- **WHEN** an engineer reads the cost statement before provisioning
- **THEN** per-delivery cost, idle cost, the dominant resources, and the estimate's date and region are all present

#### Scenario: Estimate is stale

- **WHEN** the cost estimate is older than the stated review interval
- **THEN** the documentation marks it as unverified rather than presenting it as current

### Requirement: Runbook covers the full delivery cycle

The runbook SHALL cover environment bring-up, data seeding, the presentation sequence, reset between deliveries, and teardown. Each phase SHALL state its expected duration and the observable result that confirms it succeeded.

#### Scenario: Engineer prepares a delivery

- **WHEN** an engineer follows the bring-up phase against a fresh subscription
- **THEN** each step names its expected duration and confirming observation
- **AND** the phase ends with a demo environment matching the documented ready state

#### Scenario: Phase does not reach its confirming observation

- **WHEN** a phase completes without producing its stated observable result
- **THEN** the runbook directs the engineer to the diagnostic for that phase rather than to the next step

#### Scenario: Engineer has no access to the author

- **WHEN** an engineer completes a delivery cycle using only the published documentation
- **THEN** no step requires knowledge absent from the repository

### Requirement: Presentation sequence maps to capability behavior

The presentation sequence SHALL follow the seven demo steps — ingest, stage, process, build the variant store, query, visualize, govern — and each step SHALL name the specific observable output that the corresponding capability spec requires.

#### Scenario: Presenting the staging step

- **WHEN** the engineer reaches the staging step
- **THEN** the runbook names source, destination, transfer state, integrity result, storage tier, and classification as the outputs to show

#### Scenario: Capability behavior changes

- **WHEN** a capability spec changes an observable output
- **THEN** the runbook step that demonstrates it is updated in the same change

### Requirement: Failure paths are rehearsed, not improvised

The runbook SHALL include the deliberate failure demonstrations the specs call for — a failed transfer, a rejected variant record, a denied access attempt — with the steps to trigger each and the expected system response.

#### Scenario: Demonstrating a denied access attempt

- **WHEN** the engineer triggers the access-denial demonstration
- **THEN** the runbook states how to trigger it and what the system is expected to return
- **AND** the response matches the governance spec's stated behavior

### Requirement: Reset between deliveries

The demo SHALL be resettable to its documented starting state without redeploying infrastructure, and a reset SHALL leave no records from the prior delivery visible in the variant store, metadata store, or run history.

#### Scenario: Second delivery on the same environment

- **WHEN** an engineer resets after a delivery and starts the sequence again
- **THEN** the environment presents the documented starting state
- **AND** no variant records, runs, or issues from the prior delivery are visible

#### Scenario: Reset is interrupted

- **WHEN** a reset fails partway
- **THEN** the runbook provides a way to determine which stores are clean and which are not

### Requirement: Teardown leaves no billable resources

Teardown SHALL remove every resource the demo created, and SHALL state which resources continue to incur cost if teardown is skipped.

#### Scenario: Engineer tears down after delivery

- **WHEN** teardown completes
- **THEN** no resource created by the demo remains in the target subscription

#### Scenario: Teardown is deferred

- **WHEN** an engineer chooses to keep the environment between deliveries
- **THEN** the runbook states which resources accrue cost while idle and the approximate daily rate

### Requirement: Claim boundaries are stated for the pitch

The repository SHALL carry a claim register stating what may be said about the accelerator and what may not, covering the released-blueprint boundary, the compliance boundary, the customer-reference boundary, and the clinical-use boundary. Presenter-facing material SHALL be reviewable against it.

#### Scenario: Engineer prepares a customer pitch

- **WHEN** an engineer consults the claim register before a customer conversation
- **THEN** it states, for each boundary, the supported phrasing and the phrasing to avoid

#### Scenario: New material is reviewed

- **WHEN** presenter-facing material is added or changed
- **THEN** it is checked against the claim register before release

#### Scenario: Customer asks whether this is a Microsoft product

- **WHEN** the question of product status arises
- **THEN** the claim register supplies the accurate answer: an accelerator and reference architecture built from validated patterns, not a released blueprint or a confirmed end-to-end deployment

### Requirement: Talk track separates demonstrated from asserted

Presenter guidance SHALL distinguish what the demo actually shows from what is described as a production consideration, and SHALL carry the positioning constraints so that no delivery claims a released blueprint, a compliance outcome, or an unverified customer reference.

#### Scenario: Presenter reaches a production consideration

- **WHEN** the talk track covers behavior the demo environment does not exercise
- **THEN** it is marked as a production consideration rather than presented as demonstrated

#### Scenario: Positioning review

- **WHEN** the talk track is reviewed against the claim register
- **THEN** it contains no compliance claim, no released-blueprint claim, and no unverified customer attribution

### Requirement: Demonstrated scope is separated from architectural intent

The repository SHALL state which capabilities the demo environment actually exercises and which are specified but not built, so that an engineer never presents an unbuilt capability as working software.

#### Scenario: Engineer checks coverage before presenting

- **WHEN** an engineer reviews what the demo covers
- **THEN** each capability is marked as demonstrated, partially demonstrated, or specified only

#### Scenario: Capability is specified but not built

- **WHEN** a capability has no implementation in the demo environment
- **THEN** it is listed as specified only, with what a customer conversation may claim about it

### Requirement: Known limitations are published

The repository SHALL publish the limitations an engineer will hit, including platform constraints that shaped the design, the synthetic nature of the data, and any step that requires manual intervention. Each SHALL state whether it is inherent to the platform or specific to the demo configuration.

#### Scenario: Engineer encounters a documented limitation

- **WHEN** an engineer hits a constraint during preparation
- **THEN** it appears in the published limitations with its cause and any workaround

#### Scenario: Customer asks about a limitation

- **WHEN** a customer asks whether a limitation applies to their production deployment
- **THEN** the limitation entry states whether it is inherent to the platform or specific to the demo configuration

### Requirement: Support expectations

The repository SHALL state that it is a demo accelerator carrying no support commitment, and SHALL provide the route for an engineer to report a defect that blocked a delivery.

#### Scenario: Engineer finds a defect

- **WHEN** an engineer encounters a defect during preparation
- **THEN** the documentation names where to report it and what to include

#### Scenario: Engineer expects a service level

- **WHEN** an engineer looks for a support commitment
- **THEN** the documentation states that none is offered and distinguishes the accelerator from a supported Microsoft offering
