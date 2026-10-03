# Engine — suivi capacités / manquants

Liste vivante. Mettre à jour après chaque live, smoke TF, ou chantier fermé.
Dernière revue : **2026-10-01** (raisonnement Nemotron vs `max_tokens`, garde `-x`, en-têtes de diff).

Rapports et CSV cités ici : `packages/engine/evidence/` (versionné, index de provenance dans son `README.md`).

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
| C18 | Raisonnement par classe d'appel (`NGE_THINKING_SHORT` / `_PATCH`) + `reasoning_tokens` au ledger | **OK** | `bench/thinking_ab.py` live : slot-fill 0/6 → 12/12 ; patch 8192 = 0 contexte inventé |
| C19 | Slot-fill ne peut plus réduire le run (`-x`, `-k`, `--maxfail`…) → `slotfill_narrowed` | **OK** | live : 5 pannes vues au lieu de 2 ; tests |
| C20 | En-tête de diff sans `--- `/`+++ ` restauré | **OK** | live : 0/6 → 9/9 parsés (raisonnement off) |
| C21 | Taxonomie 0b : bucket **T**, décision sur le live seul | **OK** | 11/11 sondes |
| C22 | Banc `bugbench` : 6 bugs OS-indépendants, cas cachés jamais montrés au modèle | **OK** | live : chaque patch vérifié = vrai correctif (16/16), 0 régression |
| C23 | Slot-fill : option connue mais valeur vide/invalide (`--tb=`) refusée | **OK** | live : shard exit 4, 2 bugs invisibles ; tests |

---

## Manquants / améliorations

| Id | Item | Priorité | Notes |
|----|------|----------|-------|
| M1 | **Vrai H100/H200** (Nebius Compute VM) | **P0** | plan phases 0→3 ; spawn = Go € séparé |
| M2 | Brancher SDK Compute (SA, create/delete, probe SSH) | **P0** | Phases 0 et 1 **vertes** 2026-10-03 (clé acceptée ; inventaire 9 régions ; cible L40S eu-north1) · **next : Phase 2 sur Go** |
| M3 | ~~Probe TF run complet~~ | **OK** | fermé 2026-09-05 |
| M4 | Image CUDA Contree (deps only) | **P2** | |
| M5 | DCGM dans le nœud | **P2** | |
| M6 | Patch multi-tour si truncated | **P2** | cause n°1 levée (budget mangé par le raisonnement) ; encore 2/9 coupés à 8192 |
| M18 | ~~Preuves juges dans `out/` gitignoré~~ | **OK** | fermé 2026-10-01 : `packages/engine/evidence/` + `tests/test_evidence.py` |
| M19 | ~~Pannes live = tests écrits pour Windows~~ | **OK** | fermé 2026-10-01 : `bench/bugbench` (6 bugs semés, contrôle caché) |
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
| 2026-09-23 | Fixes `demo_personal` (ordre deepseek/Ollama) + self-heal qui volait le nœud d'un shard à venir | 359 tests |
| 2026-10-01 | Cause du live 0/3 : 99 % des tokens de sortie = raisonnement | 14/15 appels coupés par le plafond |
| 2026-10-01 | **thinking_ab** 2 séries × 3 runs réels | défauts : short **off**, patch **on @8192** ; 1 vrai fix vérifié (`ntpath`) |
| 2026-10-01 | Bugs révélés : `-x` (2 bons patchs rejetés à tort) + en-têtes sans préfixe | corrigés ; 398 tests |
| 2026-10-01 | `--live --shards 2 --heuristic-plan` défauts neufs | 5 pannes, 3 patchs produits, 0 coupé, 3 rejetés honnêtement · ~$0.016 |
| 2026-10-01 | Preuves versionnées `packages/engine/evidence/` + `test_evidence.py` | clone Windows profond OK (chemins ≤ 60) |
| 2026-10-01 | **bugbench** 4 bras × 3 runs réels | patch off = on @8192 : 16/18 corrects (cachés) ; avant : 12/16 ; off ≈ 29 % du coût ; défaut inchangé |
| 2026-10-01 | Bug révélé : le modèle recopie `--tb=` du prompt | shard exit 4, 2 bugs non vus ; corrigé (valeur vérifiée + prompt) |
| 2026-10-01 | **Compute Phase 0** outillage | SDK `nebius` 0.6.17 ; preflight réécrit sur les vraies voies d'auth du SDK ; projet Compute séparé (`aiproject-` refusé) ; `.nebius_*` gitignorés ; `ready_for_wire=false` faute de credentials |
| 2026-10-03 | **Compute Phase 0 verte** | org AI Cloud + projet `project-…` ; solde 25 $ + budget 10 $ ; SA `nge-compute-readonly` (viewers) ; clé publique uploadée, privée locale ; `keygen` / `credentials` ajoutés ; validation hors ligne seulement |
| 2026-10-03 | **Compute Phase 1 verte** | `inventory` : clé acceptée par Nebius ; projet initial eu-west2 = B300 seule ; 9 régions lues ; cible Phase 2 L40S `gpu-l40s-a` eu-north1, image `ubuntu24.04-cuda13.0` ; 0 ressource créée |
| 2026-10-03 | Compute Phase 2 : code prêt, **pas lancé** | `compute_probe.py` (delete dans un `finally`, deadline 30 min, étiquette + `cleanup`), SA `phase2` séparé ; 0 VM créée |
| 2026-10-03 | **Phase 2, 1er live** (Go) | VM L40S créée en 49 s ; `nvidia-smi` manuel = **L40S 23 °C** ; sonde muette 28 min (`\r\n` Windows) ; process tué par le superviseur → `finally` sauté ; `cleanup` à +36 min ; ~1 $ ; 0 ressource restante (vérifié) |
| 2026-10-03 | Fixes Phase 2 | octets LF ; échecs SSH journalisés ; auto-extinction cloud-init à max+5 min ; refus si VM étiquetée existante |

---

## Prochaines actions (ordre)

1. **Compute Phase 2** — 1 VM L40S eu-north1, 30 min max, `nvidia-smi`, delete dans un `finally` — **payant (~0,80 $), sur Go explicite** (`docs/COMPUTE_GPU.md`)
2. **Répéter oral** juges (mock A2 + `RISKS_TO_STRENGTHS.md`)
3. **Compute Phase 1–2** seulement après Go budget explicite (1× H100 éphémère)
4. Vision perso AutoResearch — inchangé, hors juges
