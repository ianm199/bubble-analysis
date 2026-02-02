# Add --strict Mode to routes-to Command

## Issue

The `routes-to` command currently lacks the `--strict` flag that `escapes` has. This causes noisy results when name-based fallback resolution creates spurious connections.

## Example of the Problem

Running `bubble fastapi routes-to KeyError` on Airflow produced:

```
providers/microsoft/azure/.../data_factory.py:145 in get_field()
    -> GET /runs/{dag_id} (get_grid_runs)
    -> DELETE /{variable_key:path} (delete_variable)
    ... 30+ routes
```

The Azure provider's `get_field()` function is matched by name to unrelated code that calls *some* `get_field()` somewhere, creating false connections to 30+ routes.

## Current State

```bash
# escapes has --strict
bubble escapes my_function --strict  # ✓ Works

# routes-to does not
bubble fastapi routes-to ValueError --strict  # ✗ "No such option: --strict"
```

## Requested Behavior

Add `--strict` flag to `routes-to` that filters the call chain to only include high-confidence resolutions (import, self-method, constructor tracking) and excludes name-based fallback matches.

## Implementation

The `routes-to` logic in `integrations/queries.py` should accept a `resolution_mode` parameter (like `escapes` does) and filter the propagation results accordingly.

## Priority

Medium - Improves signal-to-noise ratio for large codebases with common function names.

## Related

- Dogfooding: Airflow `routes-to KeyError` produced noisy results
- Existing `--strict` implementation in `escapes` command
