# Bridge A→B — contrat harnais → train

**Version :** voir `VERSION.json` (hashes SHA-256).  
**Loi :** contrat défini dans ce fichier (exact match ≥ 90%, cf. ci-dessous).

## Fichiers

| Fichier | Rôle |
|---------|------|
| `tool_schemas.json` | Export des 8 outils (`TOOL_SCHEMAS`) — source de vérité args |
| `mini_prompt.txt` | Mini-prompt verbatim ; placeholder `{TASK}` ; ≤150 tok sans tâche |
| `parse_check.py` | Oracle : importe `_parse_text_tool_calls` ; exact = strict (dégradé=FAIL) |
| `parse_vectors.json` | ~22 vecteurs valid / invalid / degraded |
| `VERSION.json` | bridge_version + hashes |
| `export_bridge.py` | Régénère schemas + VERSION depuis le code |

## Exact match (seuil 90%)

`parse OK` + `arguments` objet strict + `name` gold + args **required** égaux.  
Fallback `arguments` string non-JSON → `{"command":...}` = **degraded** = **FAIL** exact.

## Régénérer après changement harnais

```powershell
cd ...\nodus_nanochat
python bridge/export_bridge.py
python bridge/parse_check.py
```

Si un hash change → **invalider corpus + held-out** côté train.

## Pont PLAN (2026-07-23) — NODUS planificateur

**Loi :** NODUS fournit les **noms d'outils seulement** (contrat ci-dessous).

| Fichier | Rôle |
|---------|------|
| `plan_prompt.txt` | Prompt verbatim (= prompt train, vérifié) ; `{TASK}` ; 63 tok |
| `parse_plan.py` | Parseur de référence array de noms ; `parse_plan` + `score_plan` |
| `plan_vectors.json` | 12 vecteurs valid / degraded / invalid |
| `PLAN_VERSION.json` | version + hashes + chiffres mesurés (v5 : 119/120 exact sur holdout frais) |

Checkpoint : `checkpoints/checkpoint_sft_plan_v5.pt` (v5 promu 2026-08-15 ;
v2b archivé SHA cdb94e08…).
Contrat : NODUS fournit les **noms d'outils seulement** ;
le harnais (`nodus_plan_slotfill.py`) peut pre-remplir la **cible primaire**
une etape a la fois via l'executeur (`think=false`) ; le reste des args =
executeur. Plan = suggestion a verifier ; `label != "valid"` → fallback cloud.

### Intégration harnais (P0 + P1 slot-fill)

```powershell
# A/B : source de plan (+ slot-fill ON par defaut avec nodus)
python nodus_agent.py "lis X puis edite Y ..." --plan --plan-source nodus -v
python nodus_agent.py "..." --plan --plan-source nodus --no-plan-slotfill -v
python nodus_agent.py "..." --plan --plan-source cloud -v   # defaut
python nodus_agent.py "..." --plan --plan-source off -v

# Override checkpoint
$env:NODUS_PLAN_CKPT = "checkpoints\checkpoint_sft_plan_v5.pt"

# Device planificateur (auto|cpu|cuda) — defaut auto (= GPU si dispo)
# Branche cpu mise de cote 2026-07-25 (rame avec executeur Ollama, 9B et 2b).
# $env:NODUS_PLAN_DEVICE = "cpu"
```

Modules : `nodus_plan_local.py` (inference + suggestion noms),
`nodus_plan_slotfill.py` (cibles une etape a la fois), `nodus_auto_model.py`.
Politique : `valid` → injecte suggestion (+ cibles si slot-fill) ; sinon
fallback cloud sans casser le run.

### Garde-fou carry-the-path (P1-A1)

Au-delà du slot-fill, un **garde-fou déterministe** (`carry_previous_path_targets`
dans `nodus_verify.py`, câblé dans `nodus_agent._prepare_run`) porte la cible
d'un `read_file`/`glob` vers le `edit_file`/`write_file` qui suit quand le
slot-fill a laissé `None` :

- `["read_file", "edit_file"]` avec cibles `[None, None]` sur la tâche
  « lis server.py puis change le port » → l'exécuteur reçoit
  `[None, "server.py"]` : l'edit vise le fichier qui vient d'être lu.
- **N'écrase pas un fichier NEUF** : si la tâche demande d'écrire un fichier
  distinct (`write b.txt` après `read a.py`), la cible portée n'est PAS réutilisée
  (`extract_expected_files` tranche) — le basename différent protège l'écriture.
- Toujours pur, idempotent, `len` conservé.

Ce garde attaque directement les résidus mesurés du planificateur (81/100 held-out
v2b) : ~11/19 résidus sont des `edit_file` → `bash` où l'edit manquait sa cible
(y04 read→edit, y10 glob→edit, z-série read→edit→…). Le plan reste une
suggestion de noms ; l'exécuteur garde la main sur les args réels.

```powershell
python bridge/parse_plan.py    # 12/12 vectors attendus
```
