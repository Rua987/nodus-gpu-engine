# Risques → forces (perso / local)

> **Hors pack juges obligatoire.**  
> Ne pas coller tel quel dans Devpost. Sert à **toi** : oral, Q&A, et ne pas se faire surprendre par une critique type Gemini.  
> Dernière écriture : **2026-09-08**.

Principe : un risque **nommé + borné** devient une **force** (« on a choisi la sécurité / l’honnêteté / le coût »).  
Un risque **caché** devient une faiblesse dès qu’un juge appuie dessus.

---

## Tableau rapide

| Risque (critique) | Force à dire | Phrase EN (oral) |
|-------------------|--------------|------------------|
| Plan 324M fragile / gate autofix | Le plan **décide** ; on ne patch pas sans `edit_file` | « The planner is not decoration — no edit in the plan, no code agent. » |
| Heuristique / `--heuristic-plan` | Deux modes : 324M réel **ou** film patches | « Same engine; different plan source — we show both outcomes. » |
| Contree ≠ H100 ; heal gated | Honnêteté métriques (`cpu-fallback`) | « We refuse fake thermal heal on CPU sandboxes. » |
| Migrate = re-run shard, pas teleport sandbox | Simplicité + vérité ops | « We re-run the shard on a healthier node — we don’t pretend to live-migrate sandbox state. » |
| Placement avant migrate | Pas fire→fire | « We score the destination before moving work. » |
| Patch strict (rejette si casse 1 test) | Sûreté > greenwash | « We keep only patches that stay green — 2/3 is honesty, not failure. » |
| Plafond fixes / tokens Super | Budget maîtrisé | « Bounded retries and max_tokens — no unbounded repair loops. » |
| API / quota mid-flight | Failover Nano→Super, pas Super→Nano silencieux | « On 404/5xx we hop once to Super and log it — never silent downgrade. » |
| Cold start Contree | Retry + image slim assumée | « Isolation costs cold start; we retry uploads and keep the image honest. » |

---

## Détail : transformer chaque point Gemini

### 1. 324M = goulot

**Risque :** mauvais plan → mauvais pipeline ; sans ckpt → heuristique.

**Force :**  
- Séparation claire **cerveau plan local** vs **Nemotron cloud**.  
- Gate autofix = preuve que le DSL compte.  
- Démo A (324M, souvent triage) vs A2 (`--heuristic-plan`, patches) = même moteur, deux outcomes.

**Ne pas dire :** « le 324M est parfait ».  
**Dire :** « s’il se trompe, on le voit — et on refuse d’inventer des edits. »

### 2. Sandbox / migration

**Risque (Gemini) :** « transférer l’état du sandbox ».  
**Réalité code :** relancer la commande sur un nœud choisi (placement).

**Force :**  
- Modèle mental simple, testable, filmable.  
- Pas de magie « live migrate » non implémentée.  
- Placement = on ne déménage pas vers une maison déjà en feu.

**Dire :** « re-run on a healthier node after placement — not teleport. »

### 3. Auto-fix strict + tokens

**Risque :** frustration sur refactors ; coût Super.

**Force :**  
- Critère clair (comme plus tard `val_bpb` en vision perso).  
- `MAX_FIXES`, retries patch, `max_tokens`, ledger usage.  
- Rapport **why / cause / urgency** = on explique les non-patches.

**Dire :** « 2/3 verified beats a fake 3/3. »

### 4. Live clés / quotas / réseau

**Risque :** blocage mid-run.

**Force :**  
- Événements honnêtes (`model_unavailable`, failover).  
- Track Nebius only (`NGE_TRACK=nebius`).  
- Mock = démo juges sans dépendre du réseau.

**Dire :** « Mock for the story; live for Nebius proof — failures are logged, not hidden. »

---

## Ce qu’on assume comme limite (force = transparence)

| Limite | On l’assume comment |
|--------|---------------------|
| Pas de vrai heal thermique en Contree | Archi A : Compute plus tard ; TF = exec |
| Pas d’AutoResearch dans la soumission | Doc `AUTORESEARCH_VISION.md` perso only |
| Pas de SkillSpector câblé | Jail runtime ; scan skills = option perso |
| Pas de reprise mid-train GPU | Hors scope pytest ; vision train = autre hangar |

---

## Mini script Q&A (si on attaque sur un « défaut »)

**« Votre plan est trop faible. »**  
→ « That’s why autofix is plan-gated. Weak plan → triage only. Strong plan with edit_file → patch and verify. »

**« Votre migrate est naïf. »**  
→ « We don’t claim live sandbox migrate. We place, then re-run the shard. Destination is scored first. »

**« Pourquoi seulement 2/3 ? »**  
→ « One failure had no patch — we report the symptom and urgency instead of inventing a fix. »

**« C’est du mock. »**  
→ « Mock shows the loop. Live hits Token Factory + Nemotron. We gate heal when there’s no real GPU telemetry. »

---

## Lien fichiers

| Fichier | Rôle |
|---------|------|
| `JUDGE_DRY_RUN.md` | Film + oral juges |
| `AUTORESEARCH_VISION.md` | Horizon perso (hors juges) |
| **Ce fichier** | Risques → forces (perso) |
| `ENGINE_BACKLOG.md` | État prouvé / manquant |

---

## Règle d’or

> **Mesurer et nommer** le défaut → le présenter comme **choix de design**.  
> Le transformer en force, ce n’est pas mentir : c’est montrer que tu **maîtrises** le trade-off.
