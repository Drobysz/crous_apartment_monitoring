# Monitoring filter audit

## Canonical values

- Price bounds are stored as integer euro cents (`price_min_cents`, `price_max_cents`).
- Surface bounds are stored in square metres (`surface_min_m2`, `surface_max_m2`).
- Accommodation format is stored only as `individual` or `colocation`; no translated label is persisted.
- Missing filter fields on a saved search mean that the corresponding restriction is not active.

## Corrections

| Area | Previous behaviour | Corrected behaviour |
| --- | --- | --- |
| Price parsing | Parsed with binary `float` and required two endpoints. | Parses `Decimal` values and converts directly to integer euro cents. Accepts a range, a minimum (`≥300`), or a maximum (`≤650`). |
| Surface parsing | Required two endpoints. | Supports independent inclusive bounds and comma or dot decimal separators. |
| Validation | Returned one generic error. | Rejects negative input, inverted bounds, excessive money precision, invalid syntax, and configured-limit breaches with stable codes for localized messages. |
| Inclusive matching | Behaviour was implicit. | Boundary comparisons remain explicitly inclusive for price and surface. |
| Format storage | New selections used `individuel`, a translated-looking legacy value. | New selections store `individual`; a migration normalizes existing records and the matcher continues to understand legacy `individuel` records. |
| Saved-settings display | Assumed both sides of a bound existed. | Shows only the active side with `≥` or `≤`, preserving unrelated filter values. |
| Reset all | Cleared every filter immediately. | Presents a localized confirmation; cancelling leaves every filter untouched. |

The filter tests cover exact boundaries, only-minimum and only-maximum filtering, no-bound behavior, decimal comma/dot input, invalid values, legacy format compatibility, both accommodation formats, and matching against representative CROUS listings.
