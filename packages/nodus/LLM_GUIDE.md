# 🤖 Guide des LLMs — nodus_nanochat

> **Pourquoi ce fichier ?** Éviter de perdre 30min à tester chaque modèle.  
> Benchmark réalisé le 2026-06-11 sur des tâches réelles via `nodus_agent.py`.

---

## TL;DR — Choix rapide

| Besoin | Modèle |
|---|---|
| Tâche complexe multi-étapes (fiabilité requise) | `qwen3.5:2b` ✅ |
| Tâche simple rapide (1-2 tools, vitesse prime) | `granite4.1:3b` ⚡ |
| **Fiabilité réelle (faire briller la boucle)** | **API: `claude-*` ou `deepseek-chat`** 🔥 |
| Génération de code sans tools | `deepseek-coder:latest` |
| Raisonnement / explication sans tools | `deepseek-r1:8b` |

---

## Backend API (modèles capables)

`nodus_agent` route automatiquement selon le nom de modèle (`nodus_backends.py`) :

| Modèle | Backend | Clé requise |
|---|---|---|
| `claude-*` (ex: `claude-sonnet-4-5`) | Anthropic | `.anthropic_api_key` ou `ANTHROPIC_API_KEY` |
| `deepseek-chat`, `deepseek-reasoner` | DeepSeek | `.deepseek_api_key` ou `DEEPSEEK_API_KEY` |
| tout le reste (`qwen3.5:2b`, `granite…`, `deepseek-coder:latest`) | Ollama local | — |

**SÉCURITÉ** : les clés ne sont JAMAIS dans le chat ni commitées. Placer la clé
dans un fichier `.{provider}_api_key` (gitignored) ou la variable d'env.

```bash
# Exemple : faire tourner NODUS sur Claude
echo "VOTRE_CLE" > .anthropic_api_key   # jamais collée dans le chat
python nodus_agent.py "1. compte les def  2. write_file result.txt" \
  --model claude-sonnet-4-5 --skills --verify --reflect
```

État : backend **câblé et testé** (570 tests, 100%). Un appel live DeepSeek a
renvoyé HTTP 401 (clé placeholder) — la requête est bien formée, il ne manque
qu'une vraie clé. Anthropic = traduction de format complète (tools, tool_use,
tool_result) testée avec HTTP mocké.

---

## Support de l'API tools Ollama

L'agent (`nodus_agent.py`) utilise l'endpoint `/api/chat` avec le champ `tools`.  
**Tester rapidement** si un nouveau modèle supporte les tools :

```python
import requests
resp = requests.post("http://localhost:11434/api/chat", json={
    "model": "NOM_DU_MODELE",
    "messages": [{"role": "user", "content": "ok"}],
    "tools": [{"type": "function", "function": {"name": "t", "description": "t", "parameters": {"type": "object", "properties": {}}}}],
    "stream": False
}, timeout=30)
print("OK" if resp.status_code == 200 else f"NON SUPPORTÉ ({resp.status_code})")
```

| Modèle | Tools | Notes |
|---|---|---|
| `qwen3.5:2b` | ✅ | Défaut de nodus_agent — fiable |
| `hermes3:8b` | ✅ mais bruyant | API tools OK, fiabilité agent médiocre (mesuré 2026-07-23) : ~50-60% lot facile, **0/12 lot dur**, échecs verify, très stochastique à temp défaut (±4/50 run à run). Ne pas utiliser pour A/B sans `NODUS_TEMPERATURE=0`. Cf. `reports/plan_source_ab_*.md` |
| `granite4.1:3b` | ✅ | Rapide mais hallucine (voir ci-dessous) |
| `huihui_ai/qwen3.5-abliterated:9b` | ✅ | **IMPRATICABLE** sur cette machine: ~1-2 min/appel, 13+ min sans finir une tâche A/B même avec timeout=300s. Ne pas réutiliser pour l'agent ici. |
| `dolphin3:latest` | ❌ | HTTP 400 |
| `deepseek-coder:latest` | ❌ | HTTP 400 |
| `deepseek-r1:8b` | ❌ | HTTP 400 |
| `qwen3-vl:8b` | ❓ | Timeout avant réponse |
| `embeddinggemma:latest` | ❌ | Embedding only, pas de chat |

---

## Benchmark : qwen3.5:2b vs granite4.1:3b

Tâche : `run pytest → extraire résultat → write_file → read_file`

| Critère | `qwen3.5:2b` | `granite4.1:3b` |
|---|---|---|
| Tool calls | 6 | 2 |
| Rounds | 7 | 3 |
| Temps | 72.9s | **17.7s** |
| Résultat pytest | ✅ `162 passed` (correct) | ❌ `44% passed` (confond la barre de progression avec un score) |
| Date système | ✅ `2026-06-11 16:18:08` | ❌ `2025-08-14` (inventée) |
| Suit toutes les étapes | ✅ | ❌ skip des étapes |
| Résilience sur erreur bash | ✅ tente une alternative | ❌ invente ou s'arrête |

**Verdict** : Granite est 4× plus rapide mais **hallucine les données**. Pour toute tâche où le résultat doit être exact, utiliser `qwen3.5:2b`.

### Test E2E réel (2026-06-12) — tâche write_file multi-étapes

Tâche A/B : `1. bash grep -c "^def "  2. write_file: create result.txt`.
Aucun des deux modèles n'a réellement créé le fichier :

| Modèle | Comportement observé sur l'étape write_file |
|---|---|
| `qwen3.5:2b` | Shell-out via bash en boucle → bash échoue 3-4× → max_rounds, fichier jamais créé |
| `granite4.1:3b` | **Hallucine l'appel write_file** : prétend "j'ai écrit 82 dans result.txt" (puis 17667 au run suivant) sans jamais appeler l'outil. Comptes inventés. |

### Skills (méta-codage par le maître) — A/B mesuré (2026-06-12)

Test : même tâche write, RUN A sans skills, RUN B avec skills injectées.

| Modèle | RUN A (sans skills) | RUN B (avec skills) | Effet |
|---|---|---|---|
| `qwen3.5:2b` | 8 rounds, bash échoue **7×** | 2 tool calls, **0 échec bash** | ✅ skills éliminent le thrashing bash, mais dérive → fichier non créé |
| `granite4.1:3b` | ment sur l'écriture | ment encore | ❌ skills = savoir, pas honnêteté |

**Conclusion skills** : le transfert de compétence a un effet RÉEL et mesurable
sur le comportement (qwen passe de 7 échecs bash à 0). Mais il ne peut pas :
- guérir un modèle qui MENT (granite fabrique les tool calls)
- élever un modèle au-dessus de son plafond de capacité (qwen évite bash mais dérive)

Pièce manquante identifiée : **vérification de post-condition**. Tant que
l'agent fait confiance à la CLAIM du modèle ("j'ai écrit le fichier") au lieu
de VÉRIFIER la réalité (le fichier existe-t-il ?), un modèle faible ou menteur
passe. La vérification force la réalité, pas la promesse.

### Verify (post-condition) — A/B mesuré (2026-06-12)

Tâche write, granite4.1:3b (le modèle qui ment). RUN A skills seules,
RUN B skills + verify :

| | RUN A (sans verify) | RUN B (avec verify) |
|---|---|---|
| stopped_reason | **done** | **max_rounds** |
| answer | "result.txt créé avec 49" | "result.txt créé avec 79" |
| fichier réellement créé | NON | NON |
| NODUS a menti ? | **OUI (faux succès certifié)** | **NON (échec honnête)** |

**Le résultat clé** : verify ne fait PAS créer le fichier (granite n'appelle
jamais write_file — son plafond). MAIS verify transforme un FAUX SUCCÈS en
ÉCHEC HONNÊTE. Sans verify, NODUS certifie un mensonge ("done"). Avec verify,
il refuse ("max_rounds, fichier absent").

C'est le couronnement de "le chemin, LA VÉRITÉ, pas le résultat" : NODUS ne
peut pas forcer un modèle cassé à réussir, mais il REFUSE de certifier un
faux succès. Les deux moitiés de la preuve :
- test unitaire `test_verify_passes_once_file_created` : verify force la vraie
  création quand le modèle finit par appeler write_file
- live granite : verify refuse le faux succès quand le modèle ment

**Leçons empiriques** :
- Les petits modèles locaux (2-3B) ne tiennent PAS une tâche write_file
  multi-étapes de façon fiable. Le facteur limitant est le modèle, pas l'infra.
- L'infra (anti-shortcut, mémoire, réflexion, boucle de leçons) est prouvée
  correcte de bout en bout — elle brillerait avec un modèle capable.
- **Bug trouvé via granite** : off-by-one dans l'anti-shortcut guard. Le seuil
  `< required_steps - 1` laissait répondre à une étape de la fin. Corrigé en
  `_should_challenge`: une tâche à N étapes exige N tool calls.
- **Gap restant** : le guard compte les tool calls mais ne vérifie PAS que le
  BON outil a été appelé. Granite satisfait le compte (2 bash) puis ment sur
  l'écriture. Une validation par-type-de-tâche serait la prochaine étape.

---

## Comportements connus de qwen3.5:2b

### ✅ Ce qu'il fait bien
- Suit les instructions multi-étapes si le prompt est directif
- Se récupère sur erreur bash (tente glob → read_file si bash échoue)
- Extrait correctement les données de sortie de commandes réelles
- Construit des chemins absolus Windows corrects

### ⚠️ Pièges à éviter

**1. Répond de mémoire si la tâche lui semble "connue"**  
```
# MAL — il va générer du code au lieu de lire le fichier
"Lis nodus_tools.py et liste les fonctions"

# BIEN — il est forcé d'exécuter
"bash: grep '^def ' nodus_tools.py"
```

**2. bash Unix échoue sur Windows**  
```bash
# Échouent (exit code 1) :
ls, grep -r ., grep -l, find, wc, tail, tee /tmp/...

# Fonctionnent :
grep pattern fichier.py   # fichier unique OK
git *, python -m pytest, python -c "...", echo, pwd, date
```

**3. Saute les étapes si une réponse partielle suffit**  
Ajouter dans le prompt : `"do NOT skip any step"` ou `"You MUST run commands, do NOT guess."`

---

## Tâches qui marchent vs qui échouent (testé en live)

| Type de tâche | Résultat | Explication |
|---|---|---|
| `bash` séquentiels sur des fichiers spécifiques | ✅ | Output réel, impossible à deviner |
| `write_file → read_file → edit_file → read_file` | ✅ | Chaîne de dépendances claires |
| Audit routes Flask (grep + write + read) | ✅ | Données concrètes dans un seul fichier |
| Vérif config Ollama (bash + write + read) | ✅ | Résultat système non-devinable |
| `glob "**/*.py"` comme première étape | ❌ | Modèle voit la liste → répond de mémoire |
| `read_file` sur un fichier `.py` source | ❌ | Modèle lit le code → génère du code |
| Tâche multi-fichiers avec glob en step 1 | ❌ | Shortcut systématique après step 1 |

**Règle d'or** : commencer par un `bash` avec output numérique/spécifique, jamais par `glob` ou `read_file` sur du code source.

---

## Prompts efficaces

```
# Forcer l'exécution réelle (anti-hallucination)
"You MUST run commands to get the real answers - do NOT guess."

# Forcer le séquentiel
"Do these steps ONE BY ONE, one tool call per step, do not skip any."

# Recherche multi-fichiers Windows → utiliser le tool grep (pas bash grep)
grep(pattern="mot_clé", path="nodus_tools.py")

# Compter des occurrences → bash avec fichier explicite
bash: grep -c "^def " nodus_tools.py
```

---

## Système anti-shortcut (ajouté 2026-06-11)

L'agent injecte un challenge si le modèle répond sans avoir complété toutes les étapes.

### Fonctionnement

```python
MAX_CHALLENGES = 3  # injections max par tâche

# Déclenchement : le modèle répond après N tool calls, mais la tâche a M steps (N < M-1)
# → message injecté :
"You answered after only N tool call(s), but the task has M steps.
 The path is not complete. Execute step N+1 now with a tool call."
```

### Détection des étapes

`_count_task_steps(task)` détecte les patterns numérotés :
- `"1. bash ..."` / `"1) ..."` / `"Step 1: ..."` / `"bash 1:"` / `"étape 1:"`
- Retourne 1 (pas de garde) si aucune numérotation

### Événement streaming

`stream_agent()` yield `{"type": "challenge", "round": N, "steps_done": X, "steps_required": Y}` lors d'une injection.

### Limites connues

- Le garde ne détecte que les tâches **numérotées explicitement**. Tâches narratives ("fais A puis B puis C") → pas de détection automatique.
- Si le modèle fait toujours un shortcut après 3 challenges : réponse partielle acceptée (MAX_CHALLENGES atteint).
- Le prompt système (1242 chars) est volontairement compact pour éviter la latence cold-start.

---

## Architecture des modules (2026-06-12)

NODUS est maintenant un stack de 7 modules, chacun à 100% coverage :

| Module | Rôle | Fonctions clés |
|---|---|---|
| `nodus_tools.py` | 8 outils (bash, file, grep, glob, web, brave) | `dispatch_tool`, `tool_bash` |
| `nodus_agent.py` | Boucle ReAct + orchestration | `run_agent`, `stream_agent` |
| `nodus_memory.py` | Mémoire persistante inter-sessions | `load_memory`, `append_memory_entry` |
| `nodus_chat.py` | REPL interactif | `chat_loop`, `parse_input` |
| `nodus_planner.py` | Planification des tâches complexes | `needs_planning`, `parse_plan` |
| `nodus_profiles.py` | Agents spécialisés + routeur | `route_task`, `get_profile_prompt` |
| `nodus_reflect.py` | Auto-amélioration déterministe | `analyze_run`, `format_lessons` |

### Flags de run_agent / CLI

```bash
python nodus_agent.py "tâche" \
  --memory      # -M : persiste le contexte dans .nodus_memory.md
  --plan        # -p : génère un plan pour les tâches complexes
  --profile auto # -P : route vers code/debug/docs/test, ou force un profil
  --reflect     # -R : analyse la trace et affiche les leçons
  --verbose     # -v : trace détaillée

python nodus_chat.py   # REPL interactif (mémoire activée par défaut)
```

### Capacités combinables

Tous les flags sont indépendants et cumulables. Exemple le plus complet :
```bash
python nodus_agent.py "refactorise le module X puis écris les tests" \
  --memory --plan --profile auto --reflect --verbose
```
→ route le profil, génère un plan, exécute avec mémoire, analyse la trace,
   persiste leçons + résultat. Le plan pilote l'anti-shortcut guard.

---

## Configuration actuelle de nodus_agent.py

```python
OLLAMA_URL        = "http://localhost:11434/api/chat"
DEFAULT_MODEL     = "qwen3.5:2b"   # ← ne pas changer sans tests
MAX_ROUNDS        = 20
MAX_CHALLENGES    = 3              # anti-shortcut: challenges max par tâche
MAX_CONTEXT_CHARS = 15_000         # troncature historique (évite timeout)
# timeout Ollama : 300s (augmenté depuis 120s — modèle froid peut prendre 100s+)
```
