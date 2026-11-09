# Monitor evaluation history

`Condition::evaluate`, `reset` and `mark_skipped` notify an optional observer after
the existing operation. Observer exceptions are swallowed and original evaluation
exceptions propagate unchanged. No detector or condition is evaluated for display.
Observers belong to the instance's condition tree, not `SharedFrameEvaluation`.

`ScenarioRuntime` binds each condition to its existing diagnostics path, including
every rule in a sequence. The observer captures a weak history owner so conditions
that outlive their runtime cannot call a destroyed collector. Runtime access and
history snapshots share the scenario mutex. The Instance runtime and generation
are published together under its state/runtime locks.

The collector assigns a process-unique identity to each runtime and changes it when
the Bridge session changes. Reconnects and Profile applies create new runtimes.
Together with the Instance index and diagnostics path, this prevents samples,
selection and evaluation-rate baselines from carrying into another session.

Each sample has an evaluation timestamp, optional numeric value, result/status,
and event. A missing value means no measurement; zero is a measurement. Short
evaluation of a detector creates a gap, while time/count conditions and children
that actually execute during short evaluation retain their values. Unevaluated
rules receive a gap at the end of the frame. Consecutive gaps are coalesced.
Resets notify immediately, including nested resets followed by evaluation at the
same timestamp. Old values are never filled forward across gaps or resets.

Detected values are scores, elapsed/hold values are seconds, nth values count true
child evaluations, once values represent completion, and then values represent
step progress (including final completion). Other conditions use boolean results.
Numeric progress and result timelines remain separate: a skipped numeric parent
can advance without reporting a new boolean result.

Each condition retains up to 8192 samples and a 60-second window. At capacity,
compaction drops alternating flat interiors while prioritizing local extrema,
status changes and event boundaries. If an event storm still exceeds the bound,
the newest three quarters are retained. This is bounded diagnostic history, not a
lossless recording or persistent store. Expired dormant samples are omitted from
snapshots and pruned when the collector next sees that condition.

History snapshots are opt-in through `diagnostics(true)` and
`Session::instance_diagnostics(true)`. The Monitor requests them at about 10 Hz
only while visible. The Runtime selects series with an observation inside the
requested window using the last-observation timestamp. Gaps and resets alone do
not extend a series' eligibility. Explicit Inspector paths still request all
retained samples for those paths. For large previews, an index of endpoints and
extrema copies fewer samples while keeping event and state boundaries. The index
references the original bounded deques. Timer Reset timestamps are kept
separately, so the boundary can appear even without a configured Reset Rule.
The UI prepares chart geometry once per snapshot. Both shared charts use the
same time range and leave gaps at missing measurements. The result timeline has its own segments, so it cannot suggest
a boolean result for a skipped numeric measurement.

Tests use a manual clock and deterministic frames for scores, short evaluation,
hold retries, elapsed completion, counts versus edges, then transitions, once,
nested resets, errors, retention, extrema, distinct paths/owners and reconnects.
UI tests verify segment boundaries, inactive tree nodes, independent FPS baselines
and actual ImPlot draw calls in both theme palettes. UI navigation state stays out
of runtime tests.

All configured Split trees remain addressable across Split, Ended and Reset
transitions. Each responsive card has a normal evaluation chart and a separate
Reset chart. Both keep recent traces across Rule and step changes. The summary
shows current targets and the inspector's Rule selector includes inactive
groups. Click a shared trace to inspect its raw history. Inspectors allow pan/zoom and pause their time reference
during interaction; Reset view or a 15/30/60-second change resumes the live view.
Value and result plots share the inspector's X range. Hold failures insert a
display-only vertex at the observation time to show a vertical drop to zero.

See [Monitor performance](monitor-performance.md) for the reproducible snapshot,
plot-preparation and evaluator-contention measurements that motivated filtering.

The compact view projects the full diagnostics tree into one-row unary chains,
all/any branches and separate reset_when roles. Then progress and its active step
share a row, so then → all does not introduce two structural headings. Read-only
then diagnostics expose its current step and completion state without evaluation.
RuleSequence shows its active rule. The inspector retains the full tree and all
rule roots, so hidden children and past steps remain selectable. Numeric values,
instance statistics and detector comparison belong in details.

The shared charts use ImDrawList and cap visual progress at 125% of target.
They use separate polylines per Condition and segment, with a distinct state
lane for boolean data. ImPlot draws interactive Inspector graphs in raw units.
