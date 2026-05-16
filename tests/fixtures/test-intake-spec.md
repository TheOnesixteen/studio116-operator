# Add error handling to Mureka API integration

## Goal
Add proper error handling and retry logic to the Mureka API integration in kairoke.
The integration currently has no handling for network timeouts or API rate limits.

## Project
kairoke

## Agent
codex

## Delegation Mode
live_codex_scaffold_only

## Target Files
- app/mureka.py
- tests/test_mureka.py

## Steps
1. Read the current mureka.py implementation
2. Identify all external API call sites
3. Add try/except with specific error types for each call site
4. Add exponential backoff retry for transient errors
5. Add unit tests for the error paths

## Acceptance Criteria
- app/mureka.py handles TimeoutError and HTTPError without crashing
- Retry logic backs off exponentially with max 3 attempts
- tests/test_mureka.py covers at least the timeout and rate-limit error paths

## Risk Level
low

## Notes
The Mureka API key is loaded from environment — do not hardcode or log it.
