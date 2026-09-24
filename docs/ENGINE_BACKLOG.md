# Engine — suivi capacités / manquants

Liste vivante. Mettre à jour après chaque live, smoke TF, ou chantier fermé.
Dernière revue : **2026-09-05** (usage/failover + Compute creds check).

Légende : **OK** = prouvé · **PARTIEL** = code là, preuve incomplète · **MANQUE** = pas fait · **BLOQUÉ** = dépend d’un produit externe

---

## Capacités actuelles

| Id | Capacité | État | Preuve |
|----|----------|------|--------|
| C1 | Demo mock juges | **OK** | `--mock --watch` |
| C2 | Live Nemotron plafonné + usage | **OK** | `report_20260905T211401Z` Super ×3 |
| C3 | `max_tokens` / `patch_truncated` / `model_unavailable` | **OK** | tests mock HTTP |
| C4 | Pas de failover Super→Nano | **OK** | volontaire |
| C5 | Plan gate autofix | **OK** | live : autofix OFF (`bash`/`brave_search`) |
| C6 | Preflight `[capabilities]` | **OK** | banner heal gated |
| C7 | `probe_kind` honnête | **OK** | live : 3× `cpu-fallback` |
| C8 | Heal gate (0 migration sans vrai GPU) | **OK** | live 211401Z : remediations **None** |
| C9 | Seuils DC vs consumer | **PARTIEL** | code ; besoin Compute pour preuve |
| C10 | `--local` Ollama | **OK** | exit 0 |
| C11 | `--deepseek` perso | **PARTIEL** | pas de clé |
| C12 | `NGE_FLEET_IMAGE` / `HAS_GPU` / `REQUIRE_REAL_GPU` | **OK** | config + tests |
| C13 | Squelette `fleet_mode=compute` | **PARTIEL** | `compute.py` + `check_credentials()` (0 spawn) |
| C14 | Retry Contree upload (`NGE_CONTREE_RETRIES`) | **OK** | test + live e2e après timeouts |
| C15 | Ledger usage (calls/tokens/tier + routes gap) | **OK** | `format_summary` + tests |
| C17 | Placement receveur (temp/mem/util) avant migrate | **OK** | events `gpu_placement` / `gpu_placement_refused` |

---

## Manquants / améliorations

| Id | Item | Priorité | Notes |
|----|------|----------|-------|
| M1 | **Vrai H100/H200** (Nebius Compute VM) | **P0** | plan phases 0→3 ; spawn = Go € séparé |
| M2 | Brancher SDK Compute (SA, create/delete, probe SSH) | **P0** | Phase 0 creds · Phase 1 read-only |
| M3 | ~~Probe TF run complet~~ | **OK** | fermé 2026-09-05 |
| M4 | Image CUDA Contree (deps only) | **P2** | |
| M5 | DCGM dans le nœud | **P2** | |
| M6 | Patch multi-tour si truncated | **P2** | |
| M7 | DeepSeek clé + smoke | **P2** | |
| M8 | Clarifier warning `Token expires in 0 hours` | **P2** | non bloquant (run OK) |
| M9 | Live filmable juges (narration + HTML) | **OK** | `JUDGE_DRY_RUN.md` · film reco A2 · `232100Z` |
| M10 | Planner → `edit_file` / autofix film | **OK** | `--heuristic-plan` → **2/3** verified + migrate |
| M11 | Contree timeout fichiers | **PARTIEL** | mitigé par M12 ; surveiller |
| M12 | ~~Retry Contree~~ | **OK** | fermé 2026-09-05 |
| M13 | Décision archi Compute A vs B | **OK** | **A** verrouillée (Compute heal + TF exec) |
| M16 | Vision AutoResearch (perso) | **DOC** | `docs/AUTORESEARCH_VISION.md` — **hors juges** |
| M17 | Risques → forces (perso) | **DOC** | `docs/RISKS_TO_STRENGTHS.md` — oral Q&A, hors pack obligatoire |

---

## Journal (append-only)

| Date | Action | Résultat |
|------|--------|----------|
| 2026-09-05 | Live B (avant fix probe) | 3 migrations fantômes |
| 2026-09-05 | Heal gate + probe tags | 0 remediation ; `gpu_telemetry_non_gpu` |
| 2026-09-05 | Fix probe `shell=` | smoke → `cpu-fallback` |
| 2026-09-05 | `--live` sans retry | **FAIL** Contree `ApiTimeoutError` |
| 2026-09-05 | Amorçage Compute | `compute.py` + `COMPUTE_GPU.md` |
| 2026-09-05 | **M12 retry** + `--live` 3 shards | **OK** exit 0 · `report_20260905T211401Z` · `cpu-fallback` ×3 · remediations **None** · Super in=610 out=768 |
| 2026-09-05 | Usage ledger + failover Nano→Super + `check_credentials` | tests OK ; live Ultra/Nano encore route-only |
| 2026-09-05 | **tier_smoke** IDs TF corrects + 1 chat/tier | Nano+Super+Ultra **billed** · failover sim OK · Nano `finish=length` à 64 tok |
| 2026-09-05 | **B+C** max_tokens=128 + failover live 404 | 3× `pong` · Nano→Super status=404 · TOTAL in=96 out=219 · ~$0.0002 est |
| 2026-09-05 | **M9** JUDGE_DRY_RUN + mock film | HTML `report_20260905T223331Z` · plan gate OFF · migrate 02→03 |
| 2026-09-05 | **Phase 1 M10** `--heuristic-plan` | HTML `232100Z` · autofix **2/3** · pytest suite green · docs maj |
| 2026-09-10 | **Compute PLAN** archi **A** verrouillée | Phases 0→3 dans `COMPUTE_GPU.md` ; 0 spawn ; next = Phase 0 creds |

---

## Prochaines actions (ordre)

1. **Compute Phase 0** — SDK + SA + env (`ready_for_wire`) — **0 € GPU** (`docs/COMPUTE_GPU.md`)
2. **Répéter oral** juges (mock A2 + `RISKS_TO_STRENGTHS.md`)
3. **Compute Phase 1–2** seulement après Go budget explicite (1× H100 éphémère)
4. Vision perso AutoResearch — inchangé, hors juges
