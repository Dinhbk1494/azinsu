# Interpreting Maturity Reports

## Score Breakdown

| Score | Level | What it means |
|-------|-------|---------------|
| 80-100 | Senior | Finds 85%+ of IDORs, covers all IDOR types |
| 60-79 | Mid-level | Finds 65-84%, misses hard IDORs |
| 35-59 | Junior | Finds 40-64%, mostly easy IDORs |
| 0-34 | Below Junior | Misses most IDORs |

## Key Metrics

- **Recall** (most important): % of real IDORs found. Low recall = missed bugs.
- **Precision**: % of reported IDORs that are real. Low precision = false alarms.
- **F1**: Harmonic mean of precision + recall. Balanced view.

## Failure Categories

| Category | Meaning | Fix |
|----------|---------|-----|
| DISCOVERY_GAP | Endpoint never tested | Improve crawler |
| MUTATION_GAP | Wrong ID variations tried | Expand id_mutate strategies |
| COMPARISON_GAP | Didn't notice unauthorized data | Improve diffing |
| CONFIRMATION_GAP | Suspected but not confirmed | Better evidence extraction |
| REASONING_GAP | Wrong inference | Prompt engineering |

## Per-Difficulty Breakdown

- **Easy IDORs**: Should have 90%+ recall (basic numeric path/query IDORs)
- **Medium IDORs**: 60-80% is good (encoded IDs, GraphQL, nested resources)
- **Hard IDORs**: 30-50% is acceptable (referer bypass, race conditions, JWT)

## vs Senior Comparison

- **>90%** relative performance → Senior level
- **70-90%** → Mid-level
- **40-70%** → Junior
- **<40%** → Below Junior

The key gap to close is usually MUTATION_GAP (encoding) and DISCOVERY_GAP (non-standard endpoints).
