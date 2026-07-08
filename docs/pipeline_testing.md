# Apple Review Pipeline Testing

## Scope

The automated tests cover the core reliability requirements for the reusable
pipeline:

- cleaning preserves raw review text while deriving normalized hashes and
  quality features;
- repeated executions with the same source review ids do not create duplicate
  rows;
- duplicate review text is flagged in `review_quality`.

## Test Command

```powershell
python -m unittest discover -s tests
```

## Expected Result

The suite passes without network access because collector calls are mocked with
deterministic Apple review records.

Latest local result:

```text
Ran 3 tests in 0.080s

OK
```

## Reliability Notes

- Idempotency is enforced by the `reviews` unique constraint on
  `(source_app_id, source_review_id)`.
- The pipeline records every execution in `ingestion_runs`, including runs that
  only skip already-ingested reviews.
- Review text is stored unchanged in `reviews.review_text`; normalized text is
  used only to derive `review_text_hash` and quality fields.
