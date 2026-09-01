# Vendoring

## `packages/nodus/`

Snapshot of <https://github.com/Rua987/nodus> (default branch), taken 2026-09-01
via `git archive HEAD` — no history, no `.git`. Media assets (`video_cards/`,
`*.png`) were dropped; everything else is byte-for-byte upstream.

**It is not modified.** The Nodus-GPU Engine adds the `nebius:` LLM backend to
this runtime through a reversible monkey-patch
(`packages/engine/nge/backends/register.py` — `apply()` / `restore()`), so the
upstream Agentic Cinema demo (`packages/nodus/demo_agentic_cinema.py`) keeps
working unchanged.

To refresh: re-run `git archive HEAD` from a fresh clone of `Rua987/nodus` into
`packages/nodus/`, drop the media, re-run `packages/engine` tests.

## Not included here

- `packages/linus/` (model training / research) — lives in the private
  `temple-iam-monorepo`.
- `packages/gpu-agents/` — has its own repo:
  <https://github.com/Rua987/temple-iam-gpu-agents>. Its thermal / efficiency
  scoring ideas are re-implemented, small and dependency-free, in
  `packages/engine/nge/fleet/telemetry.py`.

## Origin

This repo was split out of the private `temple-iam-monorepo` (commit `4cd5f92`).
