# 🤖 NODUS Agent — ReAct multi-couches

> **Agentic Cinema submission:** use only Google Cloud AI + Grafana — see
> **[AGENTIC_CINEMA.md](AGENTIC_CINEMA.md)**. Third-party LLM backends below are
> for local development; `NODUS_HACKATHON=1` blocks them at runtime.

> Agent de codage ReAct (Think → Tool → Observe → …) avec exécuteur Google Cloud
> (Gemini / Vertex AI) et backends locaux optionnels pour le dev. 22 modules cœur,
> 100% de couverture de tests sur chacun.

Philosophie : **le chemin, la vérité, pas le résultat.** L'agent ne triche pas,
ne saute pas d'étape, et ne certifie pas un succès qu'il n'a pas vérifié.

---

## 🚀 Démarrage rapide

**Soumission hackathon (Vertex AI uniquement) :**

```bash
python demo_agentic_cinema.py --live --model vertex:gemini-2.5-flash --task-key media
```

**Développement local (hors soumission)** — Ollama et APIs tierces restent
disponibles sans `NODUS_HACKATHON=1`. Détection via `nodus_backends.detect_backend`.

```bash
# Option 1 — backend cloud (aucune install locale)
python nodus_agent.py "compte les def dans nodus_tools.py" --verbose \
  --model openrouter/z-ai/glm-5.2

# Option 2 — backend local (Ollama + un modèle tools-capable)
ollama serve
ollama pull qwen3.5:2b
python nodus_agent.py "compte les def dans nodus_tools.py" --verbose

# Chat interactif
python nodus_chat.py

# Serveur HTTP (swarm + agent)
python nodus_swarm_server.py        # http://localhost:5789
python nodus_swarm_server.py 8080   # port custom
```

---

## ⚙️ Ops: CI + Dashboard + 5min Demo

### CI automatique des rounds red-team

Workflow GitHub Actions (racine du dépôt git, **pas** dans `nodus_nanochat/`): `.github/workflows/nodus-redteam.yml`

- `working-directory: nodus_nanochat` pour tous les steps Python
- `pip install -r requirements-ci.txt` (pytest, requests, numpy, Pillow — pas torch)
- trigger `push`/`pull_request` limité aux chemins `nodus_nanochat/**`
- lance `tests/test_nodus_oracle.py`
- lance la **suite pytest complète sauf fichiers torch** (cf. section Tests & CI)
- lance `e2e_redteam23.py`, `e2e_redteam24.py`, `e2e_redteam24_mutation.py`, `e2e_redteam25.py`
- `verify_claims.py` (harnais inclus) : rejoue les gates déterministes ET refuse
  un dashboard/ledger périmé
- génère `reports/redteam_dashboard.md` + `reports/redteam_ledger.json`, uploadés en artifact

### verify-claims (show your work)

```bash
python scripts/verify_claims.py            # vérifie (exit 1 si un chiffre ne se re-dérive pas)
python scripts/verify_claims.py --write     # rafraîchit dashboard + ledger depuis le REGISTRY
```

Discipline empruntée à T3MP3ST : un chiffre qui ne se recalcule pas ne ship pas.
Le script re-dérive le score `NODUS-RT-*`, régénère le dashboard et le compare
à la copie commitée (périmé = échec), rejoue les harness déterministes + tests
oracle, et écrit un **ledger** (`reports/redteam_ledger.json`) — une entrée de
preuve par attaque (id, surface, statut, round, défense).

### Mini dashboard métriques

```bash
python scripts/redteam_dashboard.py --out reports/redteam_dashboard.md
```

Le dashboard inclut:
- score recalculable `NODUS-RT-84: 84/84 classified, 0 GAP, defense 54/54, 30 BOUND`
- couverture registre (`HOLDS/BOUND/GAP/TODO`)
- répartition par surface d'attaque
- pass rate par modèle (agrégé depuis `reports/*.md`)

### Démo reproductible en 5 minutes

```bash
python scripts/demo_redteam_5min.py
```

Exécute une passe complète: round 29, mutation sanity, génération dashboard.

---

## 🧩 Les 22 modules cœur

| Module | Rôle | Fonctions clés |
|---|---|---|
| `nodus_tools.py` | 8 outils (bash, file, grep, glob, web, brave) + gardes | `dispatch_tool`, `tool_bash`, `_confine`, `_validate_and_pin_url` |
| `nodus_agent.py` | Boucle ReAct + orchestration + classification erreurs backend | `run_agent`, `stream_agent`, `_classify_backend_error` |
| `nodus_backends.py` | Multi-backend Ollama/DeepSeek/Anthropic/OpenRouter | `detect_backend`, `chat_api` |
| `nodus_memory.py` | Mémoire persistante (+ stoïcienne) | `load_memory`, `append_memory_entry` |
| `nodus_chat.py` | REPL interactif | `chat_loop`, `parse_input` |
| `nodus_planner.py` | Planification des tâches complexes | `needs_planning`, `parse_plan` |
| `nodus_profiles.py` | Agents spécialisés + routeur (dont `security`/`research`) | `route_task`, `get_profile_prompt` |
| `nodus_reflect.py` | Leçons depuis la trace (réinjectées) | `analyze_run`, `merge_lessons` |
| `nodus_skills.py` | Compétences curées (méta-codage) | `select_skills`, `format_skills_for_prompt` |
| `nodus_verify.py` | Post-condition : fichiers ET commandes (exit 0) + anti-relecture | `extract_expected_files`, `verify_files`, `verify_commands`, `ReadPathTracker` |
| `nodus_acceptance.py` | Conformité à l'INTENTION : cas `assert` de l'humain éprouvés contre l'impl (verdict externe, dents = échouent si impl vidée) | `extract_acceptance_cases`, `plan_acceptance_check`, `acceptance_verdict`, `acceptance_challenge` |
| `nodus_oracle.py` | Vérification SÉMANTIQUE : les tests doivent rejeter le code cassé (mutation testing) | `generate_mutants`, `mutation_score`, `oracle_verdict`, `oracle_challenge` |
| `nodus_perceptual.py` | Vérification du MÉDIA (pixel) : un rendu correspond à une référence (SSIM) — avec self-test de dents | `image_similarity`, `mean_ssim`, `perceptual_verdict`, `perceptual_challenge` |
| `nodus_media.py` | Vérification du MÉDIA (structure) : propriétés ffprobe vs spec (durée/dim/codec/flux) — spec vide = vacueuse | `probe_media`, `media_properties`, `check_media`, `media_challenge` |
| `nodus_search.py` | AMPLIFICATION : best-of-N guidé par le vérificateur (récolte pass@k) | `best_of_n`, `expected_success` |
| `nodus_amplify.py` | Amplification opt-in câblée sur l'agent : N runs frais, garde le 1er CERTIFIÉ | `amplified_run`, `_verify_dir` |
| `nodus_falsify.py` | Reverse-NODUS : cherche un CONTRE-EXEMPLE exécuté (property-based/fuzz) — comble l'angle mort des cas fixes | `falsify`, `FalsifyResult` |
| `nodus_policy.py` | Régime adaptatif backend + profil : anti-paralysie, anti-thrash, read-paralysis, budget profil-conscient | `policy_for`, `should_force_write`, `should_refocus`, `should_stop_read_paralysis` |
| `nodus_knowledge.py` | Pont mémoire : découvertes rappelées par pertinence (flag `knowledge`) | `save_finding`, `recall_findings` |
| `nodus_redteam.py` | Registre VIVANT des attaques red-team (33, 0 GAP) | `REGISTRY`, `coverage_summary`, `parse_proposed_attacks` |
| `nodus_claim_check.py` | Pont SWARM→AGENT : extraire les affirmations falsifiables, bâtir leur vérif | `extract_claims`, `build_verify_task` |
| `nodus_selfredteam.py` | Boucle self-red-team : verdict ANCRÉ DANS LE CODE (jamais la parole de l'agent) | `build_attack_task`, `reconcile` |

Le serveur `nodus_swarm_server.py` expose le tout en HTTP.

---

## 🎛️ Les couches (flags cumulables)

```bash
python nodus_agent.py "TÂCHE" [options]
```

| Flag | Effet |
|---|---|
| `--memory` / `-M` | Mémoire persistante inter-sessions (`.nodus_memory.md`). Se souvient AUSSI des échecs (mémoire stoïcienne). |
| `--plan` / `-p` | Génère un plan explicite avant les tâches complexes. |
| `--profile X` / `-P` | Profil spécialisé : `code`, `debug`, `docs`, `test`, `research`, `security`, `general`, ou `auto` (routage). `security`/`research` sont *read-heavy* → budget de lecture relâché. |
| `--reflect` / `-R` | Analyse la trace, extrait des leçons, les ré-injecte aux runs suivants. |
| `--skills` / `-S` | Injecte des compétences curées (« pour écrire, utilise write_file, jamais bash »). |
| `--verify` / `-V` | Vérifie sur le disque que les fichiers promis existent ET (si la tâche l'exige) que les commandes tournent en exit 0. Refuse de certifier un faux succès. |
| `--oracle` / `-O` | Vérification SÉMANTIQUE (avec `--verify`), deux volets : **code** — casse le code (mutants) et exige que les tests ÉCHOUENT (tests vacueux rejetés) ; **média** — si la tâche nomme `<produit> matching <référence>`, compare le rendu à la référence (SSIM). Activation sur **langage naturel** : « run pytest », « make sure the tests pass » + un fichier `test_*.py` nommé suffit (plus besoin du jargon « exit 0 »). Chaque volet n'active que sur une paire non ambiguë → relance forcée sinon. |
| `--amplify N` / `-A` | **Amplification opt-in** : best-of-N runs frais, garde le 1er artefact CERTIFIÉ par les oracles (récolte pass@k). Force `--verify --oracle`. Coût × N → défaut 1 (off) ; n'amplifie que si la tâche a un signal vérifiable (acceptation/tests/référence). Mesuré : pass@1 0.40 → best-of-5 ≈ 0.92. |
| `--knowledge` / `-K` | Pont mémoire : rappelle les découvertes passées par pertinence et les ré-injecte au run courant. |
| `--playbook` / `-B` | Mémoire de chemins : réutilise les recettes d'outils prouvées + apprend les nouvelles (refait ~27% plus vite une tâche déjà faite — mesuré, n=3). |
| `--model X` / `-m` | `qwen3.5:2b` (local), `openrouter/z-ai/glm-5.2` (cloud fort), `openrouter/openai/gpt-oss-120b:free` (gratuit)… |

Exemple complet :

```bash
python nodus_agent.py "1. compte les def  2. write_file result.txt" \
  --model claude-sonnet-4-5 --skills --verify --reflect --memory
```

---

## 🛡️ Les gardes (commandement suprême)

- **Anti-shortcut** : une tâche à N étapes exige N tool calls avant de répondre.
  (Un off-by-one historique laissait répondre 1 étape trop tôt — corrigé.)
- **Verify** : avant d'accepter « j'ai écrit le fichier », on vérifie qu'il existe.
  Transforme un *faux succès* en *échec honnête*.
- **Content-verify** (`invalid_content_files`) : au-delà de l'existence, un `.py`
  qui ne *compile* pas / un `.json` qui ne *parse* pas n'est pas un livrable —
  attrapé même quand le fichier a bien été écrit (indépendant de `filter_missing`).
- **Falsify-gate** (`nodus_falsify`, avec `--oracle`) : si la tâche nomme un fichier
  de propriétés humain `*_props.py`, la gate cherche un CONTRE-EXEMPLE exécuté
  (entrées aléatoires vs invariants) — comble l'angle mort des cas FIXES (un bug
  que cas+tests ratent ensemble). Contre-exemple trouvé = code faux → relance.
- **Trim** du contexte (15k chars) → pas de timeout sur les longues tâches.
- **Sandbox / confinement** (`_confine`) : tout chemin — en **lecture ET en
  écriture** — est résolu puis vérifié comme restant SOUS le cwd de la tâche.
  Un `/etc/passwd` ou un `../../escape.txt` est refusé (anti-évasion).
- **Denylist destructrice** (`_is_destructive`) : les commandes manifestement
  destructrices et irréversibles (effacement racine, formatage, fork bomb…)
  sont bloquées avant exécution.
- **Anti-SSRF** (`_is_blocked_url`) : `web_fetch` refuse une URL dangereuse
  (loopback, réseaux privés, métadonnées cloud) AVANT la requête **et**
  re-valide chaque redirection (pas d'évasion par redirect).
- **Redaction de secrets** (`redact_secrets`) : les secrets évidents dans toute
  sortie d'outil (fichier, stdout, page web) sont caviardés avant d'atteindre
  le modèle.
- **Immunité jailbreak** (LAW dans `_SYSTEM_PROMPT`) : les patterns d'override
  (« ignore previous instructions », DAN, developer mode, « skip verification »…)
  sont nommés et refusés ; les gardes restent en CODE, indésactivables par l'input.
- **Anti-DNS-rebind** (`_validate_and_pin_url`) : `web_fetch` résout l'hôte UNE
  fois et épingle l'IP + en-tête Host → pas de re-résolution vers une cible interne.
- **Anti-thrash + read-paralysis** (`nodus_policy`) : écrire du bruit sans livrer,
  ou lire en boucle sans produire, est détecté et recentré (signal *outcome*).
- **Référence protégée** (`_protected_reference_error`) : un fichier-runner existant
  (ex. `mini_pytest.py`) n'est pas réécrasable sur un VERIFY halluciné.
- **exec-verify** (`verify_commands`) : si la tâche exige « exit 0 », la commande
  est RÉ-EXÉCUTÉE — verify dépasse l'existence du fichier.
- **oracle sémantique** (`nodus_oracle`, flag `--oracle`) : exit 0 ne suffit pas.
  On CASSE le code (mutants : `<`→`>=`, `+`→`-`, `return`→`None`…) et on exige
  que les tests ÉCHOUENT. Une suite qui passe même sur du code cassé est
  *vacueuse* → le « PASS » ne prouve rien → relance forcée. La frontière de la
  *correction sémantique* est ainsi repoussée de « les tests passent » (gameable)
  à « les tests rejettent démontrablement les défauts » — verdict ancré dans le CODE.
- **oracle perceptuel** (`nodus_perceptual`) : pendant MÉDIA du précédent. Un rendu
  (Blender, ffmpeg…) est comparé à une référence par SSIM par blocs. Même self-test
  de dents : on PERTURBE la référence et on exige que la similarité chute sous le
  seuil — sinon le seuil est vacueux. Prouvé au sol : cube vs cube = 1.00 (match),
  sphère vs cube = 0.81 (rejeté), référence perturbée = 0.64 (dents). **Branché en
  gate** via `--oracle` quand la tâche nomme `<produit> matching <référence>` :
  produit absent → `missing` (force le rendu), référence absente → abstention.
- **oracle média structurel** (`nodus_media`, ffprobe) : pendant « propriétés » du
  perceptuel, pour le pilotage ffmpeg. Confronte durée/dimensions/codecs/flux du
  fichier produit à une spec ; une spec sans contrainte = `no_constraints` (vacueuse,
  ne prouve rien). Prouvé au sol (ffmpeg réel) : spec correcte → match, spec fausse
  → mismatch avec deltas exacts. Module disponible ; gate à brancher (convention spec).

---

## 🔗 Les ponts (deux systèmes, une vérité externe)

NODUS a **deux** systèmes : l'**agent** (outils + verify, pour AGIR) et le **swarm**
(raisonnement multi-masques sans outils, pour PENSER). Trois ponts les relient — et
dans chacun, **le verdict reste externe (code/ground truth), jamais la parole de l'agent** :

| Pont | Sens | Rôle |
|---|---|---|
| **autoresearch** (`e2e_redteam_autoresearch.py`) | agent → red-team | NODUS propose des classes d'attaques hors des surfaces couvertes |
| **claim-check** (`nodus_claim_check.py`) | swarm → agent | le swarm avance des chiffres falsifiables → l'agent les PROUVE au sol (web) |
| **self-red-team** (`nodus_selfredteam.py`) | NODUS → NODUS | il attaque son propre code → le CODE tranche le verdict (témoin disque) + flague le mensonge |

> Le swarm clone sur les petits modèles et V4 ; il ne DIVERGE qu'avec Opus.
> Réserver le swarm à Opus ; l'agent tourne bien sur V4-pro (ou gratuit).

---

## 🌐 Backends

`nodus_agent` route automatiquement selon le nom du modèle :

| Modèle | Backend | Clé |
|---|---|---|
| `openrouter/<provider>/<model>` (ex: `openrouter/deepseek/deepseek-v4-pro`, `openrouter/openai/gpt-oss-120b:free`) | OpenRouter (multi-modèles, 1 clé) | `.openrouter_api_key` ou `OPENROUTER_API_KEY` |
| `claude-*` | Anthropic | `.anthropic_api_key` ou `ANTHROPIC_API_KEY` |
| `deepseek-chat`, `deepseek-reasoner` | DeepSeek | `.deepseek_api_key` ou `DEEPSEEK_API_KEY` |
| tout le reste | Ollama local | — |

Erreur backend lisible : un 429 (rate-limit), 401 (auth)… remonte en `stopped_reason`
`http_<code>` au lieu d'un générique (`_classify_backend_error`). Free = rate-limited ;
pour du soutenu → payant (V4-pro). Capacité = le modèle ; les locaux 2-8B échouent le code dur.

**🔒 Sécurité** : les clés ne sont JAMAIS dans le code ni le chat. Fichier
`.{provider}_api_key` (gitignored) ou variable d'environnement uniquement.

---

## 🌍 API HTTP

```bash
# Agent direct
curl -X POST localhost:5789/api/v1/agent -H "Content-Type: application/json" \
  -d '{"task":"write result.txt","skills":true,"verify":true}'

# Streaming (NDJSON)
curl -X POST localhost:5789/api/v1/agent/stream -d '{"task":"...","reflect":true}'

# Routage auto (agent vs swarm de raisonnement)
curl -X POST localhost:5789/api/v1/auto -d '{"task":"explique et corrige le bug"}'
```

Toutes les couches (`memory`, `plan`, `profile`, `reflect`, `skills`, `verify`)
sont acceptées dans le corps JSON.

---

## 🧪 Tests & CI

```bash
python -m pytest tests/        # suite complète (torch requis localement)
```

**Déterministe, sans Ollama ni réseau** pour la grande majorité : les tests
mockent `_chat` (modèle scripté) et exercent les outils/vérificateurs réels sur
disque. Seuls quelques tests ont besoin d'un réseau/API (rounds e2e, AB).

**CI = sans torch.** Le CI GitHub Actions ne peut pas installer torch
(CPU-only runner). Il exclut les fichiers qui l'importent au module :

```bash
python -m pytest tests/ \
  --ignore tests/test_nodus_gpt.py \
  --ignore tests/test_nodus_tokenizer.py \
  --ignore tests/test_climbmix.py \
  --ignore tests/test_worldmodel_bridge.py \
  --ignore tests/test_nodus_tools.py \
  -q --tb=short
```

Ces exclusions couvrent le planificateur/entraînement (torch) — jamais la
boucle agent/verify/slot-fill, qui reste 100% testée sans torch. `test_nodus_tools.py` importe torch au module donc il
n'est pas collectable sans torch ; `conftest.py` protège déjà
`nodus_nanochat/__init__` de l'import torch.

Couverture : les 22 modules cœur de l'agent sont maintenus à **100%**
(`--cov=nodus_<module>`, vérifié à chaque commit ; suite > 2000 tests).

---

## 📚 Voir aussi

- `LLM_GUIDE.md` — quel modèle pour quelle tâche, benchmarks réels, pièges,
  findings empiriques (qwen faible / granite menteur / 9b lent).
- `README.md` — le LLM nanochat from-scratch (autre projet du dossier).

---

**🏛️ Plus Ultra! DATTEBAYO! ⚡** — Copyright © 2024 Temple IAM
