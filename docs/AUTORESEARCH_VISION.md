# AutoResearch × Nodus-GPU Engine — vision (perso / local)

> **Hors soumission juges.**  
> Ne pas citer dans `NEBIUS_TRACK.md`, Devpost, ni le pitch Coding & Agentic Engineering.  
> Document **personnel** : horizon produit local, pas un engagement hackathon.

Dernière écriture : **2026-09-06**.

---

## Pourquoi ce doc existe

Nodus-GPU Engine sait aujourd’hui : planifier → flotte → heal/placement → patch pytest → garder seulement ce qui reste vert.

**AutoResearch** (Karpathy) = une autre boucle : modifier `train.py` → train court → mesurer `val_bpb` → garder si mieux, sinon revert → répéter.

Même **discipline** (essayer → mesurer → garder ou jeter).  
**Autre métier** (usine d’expés d’entraînement ≠ triage de tests).

Analogie : même entreprise, **autre hangar** — ne pas mélanger avec le film juges.

---

## AutoResearch en une minute

1. Lire `program.md` (instructions).  
2. Modifier le code d’entraînement (ex. `train.py`).  
3. Lancer un train court (ex. ~5 min, 1 GPU).  
4. Lire la métrique (`val_bpb` — bits per byte de validation ; **plus bas = mieux** dans le cadre ClimbMix / LINUS).  
5. Si amélioration → garder ; sinon → annuler.  
6. Boucler de façon autonome.

---

## Ce que Nodus apporterait (si on le câble un jour)

| Brique existante | Rôle pour AutoResearch |
|------------------|------------------------|
| Mission | « 20 essais » / « 8 h » / métrique / chemins `train.py` + `program.md` |
| Fleet + placement | Plusieurs GPU en parallèle (stock AR = souvent 1 GPU) |
| Jail shell | Bloquer commandes dangereuses au lancement |
| Rapport + cause / urgence | Journal : essai N, métrique avant/après, keep/discard, pourquoi |
| Nemotron (tiers) | Proposer la *prochaine* modif (hors track juges si autre provider) |
| Keep/discard | Comme les patches : critère `val_bpb_après < val_bpb_avant` |

---

## Ce qui n’est **pas** vrai aujourd’hui

- Contree Token Factory ≠ H100 d’entraînement sérieux → il faudrait **Compute** (ou machine locale).  
- Heal/migrate **ne reprend pas** un train mid-flight sans checkpoint + reprise.  
- Le jail **ne** remplace **pas** une revue de diff de `train.py` (il filtre surtout le shell).  
- Le planificateur 324M n’a pas encore les outils `run_training` / `git_revert`.  
- Aucun train AutoResearch n’est branché dans ce dépôt comme chemin juges.

---

## Mission type (brouillon — pas implémenté)

```text
Mission: Run an AutoResearch experiment (local / personal only).
- workdir: <path to train.py + program.md>
- metric: val_bpb (lower is better)
- budget: 20 trials OR 8 hours wall-clock
- parallel: 1 GPU (default) | N if fleet allows
- on_improve: keep diff
- on_regress: git revert (or equivalent)
```

Séquence d’outils **souhaitée** (futur) :  
`edit_file` → `run_training` → (`git_revert` | keep) → journal.

---

## Ordre de construction (si Go un jour — pas maintenant)

| Id | Étape | Prérequis |
|----|--------|-----------|
| V0 | Ce document | — |
| V1 | Stubs mock : parse métrique + keep/discard sans GPU | Go code |
| V2 | 1 train réel local / Compute | Go explicite + budget €/GPU |
| V3 | Multi-GPU + Nemotron « next idea » + revue diff | Après V2 mesuré |

**Règle :** aucun train long / `.ps1` / probe GPU coûteux sans **Go** explicite (rules perso / LINUS).

---

## Lien avec LINUS (si tu travailles les deux)

- `val_bpb` = métrique ClimbMix / critères go-stop déjà documentés côté LINUS.  
- AutoResearch-dans-Nodus = **orchestrer** des essais ; le train reste `train_linus_*.py` (ou équivalent).  
- Ne pas confondre avec le track Nebius juges.

---

## Phrase mémoire (perso uniquement)

« Même boucle keep/discard que les patches pytest ; demain la métrique peut être `val_bpb` sur un vrai GPU — aujourd’hui ce hangar n’est pas ouvert aux juges. »
