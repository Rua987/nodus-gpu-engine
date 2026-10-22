# Vendoring

## `packages/nodus/`

Snapshot of <https://github.com/Rua987/nodus> (default branch), taken 2026-09-01
via `git archive HEAD` — no history, no `.git`. Media assets (`video_cards/`,
`*.png`) were dropped; everything else is byte-for-byte upstream, except one
change on 2026-10-21: an old personal label in the file headers and the licence was
replaced by `Rua987`, "All Rights Reserved" in those headers became "MIT License" (the
licence the code was always under), and a test's fake search result was renamed. No code
changed.

**It is not modified.** The Nodus-GPU Engine adds the `nebius:` LLM backend to
this runtime through a reversible monkey-patch
(`packages/engine/nge/backends/register.py` — `apply()` / `restore()`), so the
upstream Agentic Cinema demo (`packages/nodus/demo_agentic_cinema.py`) keeps
working unchanged.

To refresh: re-run `git archive HEAD` from a fresh clone of `Rua987/nodus` into
`packages/nodus/`, drop the media, re-run `packages/engine` tests.

## Not included here

- `packages/linus/` (model training / research) — lives in a private monorepo.
- `packages/gpu-agents/` — has its own repo (GPU agents):
  <https://github.com/Rua987/temple-iam-gpu-agents>. Its thermal / efficiency
  scoring ideas are re-implemented, small and dependency-free, in
  `packages/engine/nge/fleet/telemetry.py`.

## Origin

This repo was split out of a private monorepo (commit `4cd5f92`).
