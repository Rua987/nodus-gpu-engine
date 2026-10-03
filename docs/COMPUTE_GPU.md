# Nebius Compute GPU — PLAN (avant tout spawn)

> **Statut : PLAN ONLY.** Aucune VM GPU tant qu’il n’y a pas un **Go budget** séparé.  
> Dernière écriture : **2026-10-03** (**Phases 0 et 1 vertes** ; prochain = Phase 2, sur Go explicite).  
> Lié : `ENGINE_BACKLOG.md` (M1/M2/M13) · `RISKS_TO_STRENGTHS.md` · `AUTORESEARCH_VISION.md` (perso).

Objectif : `probe_kind=nvidia-smi` sur un **device NVIDIA réel**, pour que heal + placement deviennent une **preuve**, pas seulement un mock.

---

## 0. Décision d’archi — **A** (verrouillée pour ce plan)

| | **A (retenu)** | B (rejeté pour l’instant) |
|--|----------------|---------------------------|
| Fleet / télémétrie / heal | **Compute** VM GPU | Tout sur la VM |
| Exécution pytest / patch | **Token Factory Contree** (déjà câblé) | SSH + pytest sur la VM |
| Pourquoi A | Moins de surface SSH ; TF déjà OK pour exec ; Compute = honnêteté GPU | Plus simple conceptuellement, plus de boulot ops |

Analogie : Contree = **atelier** où on répare le code ; Compute = **thermomètre + garage** pour les vraies machines chaudes.

---

## 1. Ce qui existe déjà (ne pas refaire)

- [x] `fleet_mode=compute` → `ComputeGpuFleet` (provision = `NotImplementedError`)
- [x] `check_credentials()` — lit env, **0 API, 0 VM**
- [x] Placement `pick_replacement` (temp/mem/util) — prêt à consommer de vrais status
- [x] Heal gated si pas `has_real_gpu_metrics`
- [x] Mock filmable + live Contree (cpu-fallback)

Dernier check creds (2026-10-01) : SDK OK, auth / projet / subnet absents → `ready_for_wire=false`.

---

## 2. Phases (ordre strict)

### Phase 0 — Prérequis (€0 machine, temps humain)
**But :** pouvoir dire « auth Compute OK » sans créer de VM.

1. ~~`pip install nebius` (SDK)~~ — **fait** 2026-10-01 (`nebius` 0.6.17 sur la machine
   de dev ; ajout pur, aucun paquet existant mis à jour). Dépendance optionnelle,
   pas dans `requirements.txt`.
2. **Auth** — une des trois, dans l'ordre où le SDK les lit (vérifié dans son code) :
   - fichier de credentials de service account :
     `packages/engine/.nebius_sa_credentials.json` ou `NEBIUS_SA_CREDENTIALS_FILE`.
     Format attendu par le SDK : `{"subject-credentials": {"alg": "RS256",
     "private-key": "<PEM>", "kid": "<id de la clé publique>", "iss": "<id du SA>",
     "sub": "<id du SA>"}}` (`iss` = `sub`). Le preflight le **valide hors ligne**
     (JSON, RS256, iss = sub, clé PEM lisible) et dit pourquoi s'il est refusé.
   - profil du CLI `nebius` (`~/.nebius/config.yaml`) ;
   - `NEBIUS_IAM_TOKEN` — la seule variable d'environnement que le SDK lit.
     (`NEBIUS_SA_KEY_FILE`, `YC_SERVICE_ACCOUNT_KEY_FILE`, `NEBIUS_FOLDER_ID` de
     l'ancien plan ne sont lus par rien : retirés.)
3. **Projet AI Cloud** : `NEBIUS_COMPUTE_PROJECT_ID` ou
   `packages/engine/.nebius_compute_project_id`. **Pas** `NEBIUS_PROJECT_ID` :
   celui-ci est le projet **Token Factory** (`aiproject-…`) qu'utilisent déjà les
   sandboxes du chemin `--live` ; l'ancien plan disait d'y mettre l'id Compute,
   ce qui aurait cassé `--live`. Un id `aiproject-…` est refusé avec la raison.
   Un id AI Cloud commence par `project-` (chaque id Nebius porte son type en
   préfixe) : un `tenantuseraccount-…` (ton compte utilisateur, proposé ici une
   première fois par erreur), un `tenant-…` ou un `serviceaccount-…` est refusé.
4. Subnet (`NEBIUS_SUBNET_ID` ou `.nebius_compute_subnet_id`) — signalé, mais
   requis seulement en Phase 2.
5. Vérifier : `python -m nge.fleet.compute` (sortie 0 = prêt) →
   `ready_for_wire=True`, `spawn_allowed` reste **False**. Aucun appel API.
6. Noter région / quotas GPU console.

Tous ces fichiers `.nebius_*` sont dans `.gitignore` (racine et `packages/engine/`).
Tests : `tests/test_compute_phase0.py` (clé RSA jetable, aucun réseau).

**Comment c'est fait (2026-10-03), dans l'ordre :**

1. Console AI Cloud (`console.nebius.com`, **pas** `tokenfactory.nebius.com` : là-bas
   les ids sont `aitenant-` / `aiproject-` et ne portent pas de VM). Organisation
   `tenant-…`, projet `project-…` → `.nebius_compute_project_id`.
2. Billing : solde AI Cloud **séparé** du solde Token Factory (top-up carte 25 $),
   budget mensuel 10 $ avec alertes 50/80/90/100 % par e-mail.
3. IAM → service account `nge-compute-readonly`, groupe **viewers** (lecture seule ;
   le droit de créer une VM sera donné à part, pour la Phase 2).
4. Onglet *Authorized keys* : la console **n'accepte qu'un upload de clé publique**
   (pas de JSON téléchargeable ; l'onglet *Access keys* donne une clé S3 id + secret,
   inutile pour Compute). Donc :
   - `python -m nge.fleet.compute keygen` — RSA 4096 ; la privée reste dans
     `.nebius_sa_private_key.pem`, jamais affichée ; la publique est imprimée et
     écrite dans `.nebius_sa_public_key.pem` pour l'upload ;
   - upload dans la console → elle rend un id `publickey-…` ;
   - `python -m nge.fleet.compute credentials --service-account-id serviceaccount-… --public-key-id publickey-…`
     assemble `.nebius_sa_credentials.json` au format du SDK et le valide (refuse un
     id `accesskey-…` ou un id de compte utilisateur).
5. `python -m nge.fleet.compute` → `ready_for_wire=True`.

**Ce que la Phase 0 ne prouve pas :** que Nebius accepte la clé. La validation est
hors ligne (format, RS256, iss = sub, PEM). Le premier appel de la Phase 1 le dira.

**Pas de spawn.**

### Phase 1 — Wire lecture seule (encore €0 GPU)
**But :** SDK parle au cloud **sans** créer d’instance.

1. ~~Client auth SA → list platforms / images (read-only)~~ — **fait 2026-10-03**
2. ~~Doc des IDs réels~~ — ci-dessous
3. ~~Tests mock du client~~ — `tests/test_compute_inventory.py` (fausse API, aucun réseau)

`python -m nge.fleet.compute inventory` : premier vrai appel avec la clé (elle est
acceptée — la Phase 0 est donc prouvée côté serveur), puis pour **chaque projet de
l'organisation** : région, plateformes GPU et presets, subnets, images CUDA
publiques. Écrit `out/compute_inventory_<ts>.json` (non versionné : il contient
les ids du compte) et propose une cible Phase 2. Uniquement des `get` / `list` /
`list_public` — un test analyse le code et échoue si un `create` / `update` /
`delete` / `start` / `stop` y apparaît.

**Ce que l'inventaire a appris (2026-10-03) :**

- Le projet donné au départ est en **eu-west2**, qui ne propose qu'une **B300**.
  L'organisation a un projet par défaut **par région** (9) ; le catalogue diffère
  par région. D'où un inventaire de toutes les régions, pas du seul projet configuré.
- Plateformes avec un preset à 1 GPU, par région :

  | région | GPU |
  |---|---|
  | eu-north1 | **L40S** (`gpu-l40s-a` 1gpu-8vcpu-32gb, `gpu-l40s-d`), **H100** (`gpu-h100-sxm` 1gpu-16vcpu-200gb), H200 ; GB300 sans preset 1 GPU |
  | eu-west1 | H200 |
  | us-central1 | RTX 6000, B200, H200 |
  | eu-west2, us-north1, uk-south1 | B300 |
  | uk-south2, eu-south1 | RTX 6000 |
  | me-west1 | B200 |

- **Cible Phase 2 retenue :** `gpu-l40s-a` / `1gpu-8vcpu-32gb` en **eu-north1**, image
  `ubuntu24.04-cuda13.0` (famille figée de la doc Nebius ; `-latest` bouge,
  `-serverless` n'est pas une image de VM, l'ordre alphabétique choisissait
  `ubuntu22.04-cuda12`), subnet par défaut du projet eu-north1.
- Listé n'est pas réservé : la capacité ne se sait qu'à la création.

**Pièges rencontrés :**

- Sous Windows, le SDK exige `certifi-win32` pour lire les certificats système et
  refuse de démarrer. On lui passe le bundle `certifi` (déjà là via `requests`)
  en `tls_credentials` — aucun paquet de plus.
- `nebius.iam.v1.ProjectService` est obsolète (supporté jusqu'au 2026-12-16) :
  l'inventaire utilise `iam.v2`.

### Phase 2 — Probe sur **1** VM éphémère (Go € obligatoire)
**But :** un `nvidia-smi` CSV → `probe_kind=nvidia-smi`, puis **destroy**.

1. Flag dur : `NGE_COMPUTE_SPAWN=1` + confirmation CLI `--i-know-cost`
2. `provision(1)` → wait READY → SSH ou agent → probe
3. `status()` remplit temp/util/mem/power + `gpu_class`
4. `release` / delete **toujours** dans un `finally`
5. Budget plafond : ex. **max 20–30 min** wall clock pour le premier essai

**Go Phase 2 :** top-up solde + phrase explicite « Go spawn 1× H100 test ».  
Sans ça → **Non**.

**Code prêt (2026-10-03), pas encore lancé** — `nge/fleet/compute_probe.py`,
`python -m nge.fleet.compute probe --i-know-cost` avec `NGE_COMPUTE_SPAWN=1` :

- cible = la recommandation de l'inventaire (L40S `gpu-l40s-a` eu-north1, image
  `ubuntu24.04-cuda13.0`, disque de boot 50 Gio SSD, IP publique dynamique) ;
- **compte de service séparé** `phase2` (groupe *editors*, il faut créer une VM) :
  `keygen --name phase2` / `credentials --name phase2`. Le compte *viewers* de la
  Phase 1 n'est jamais élargi ;
- l'id de la VM est connu dès le retour de la requête de création, avant la fin
  de l'opération : une création qui expire laisse quand même un id à supprimer ;
- suppression dans un `finally` (erreur, délai, Ctrl+C), 3 tentatives, budget de
  suppression séparé ; le rapport dit `deleted: true/false` et la CLI sort en
  code 3, bruyamment, si la suppression n'est pas confirmée ;
- un délai mural unique, plafonné à 30 min, borne chaque attente ;
- étiquette `nge-phase2=probe` sur VM et disque ;
  `python -m nge.fleet.compute cleanup` supprime tout ce qui la porte ;
- lecture : SSH par clé (ed25519 locale, `.nebius_vm_ssh_key`, utilisateur `nge`,
  `root`/`admin` étant réservés), `known_hosts` jetable, même sonde et même parseur
  que la flotte Contree → `probe_kind=nvidia-smi` là où le moteur l'attend ;
- estimation affichée avant : GPU + vCPU + RAM au tarif console (~0,77 $ HT pour
  30 min de L40S) — **disque et IP publique en plus**.

À savoir : le groupe de sécurité par défaut d'eu-north1 **autorise tout en
entrée** (lu en Phase 1). La VM est donc joignable d'internet pendant sa courte
vie ; accès par clé uniquement. Pas de console série dans l'API Compute, d'où SSH.

Tests : `tests/test_compute_probe.py` — fausse API, fausse horloge : suppression
après échec de création, SSH muet, VM jamais prête, Ctrl+C ; suppression
réessayée ; non-confirmation signalée ; plafond de durée ; refus de la CLI sans
les deux opt-in.

### Phase 3 — Brancher heal live (archi A)
**But :** orchestrateur utilise Compute pour télémétrie/remediation ; shards restent Contree.

1. `NGE_FLEET_MODE=compute` + `NGE_SANDBOX=token_factory` (hybride)
2. Pressure → placement sur status **réels** → migrate = re-run shard (comme aujourd’hui)
3. Preuve : event `gpu_remediation` avec `probe_kind=nvidia-smi` (pas synthetic)
4. Film / HTML optionnel (perso ou juges selon timing)

### Phase 4 — (optionnel, plus tard) Exec sur Compute
Seulement si Contree devient limitant. = glissement vers archi B partielle. **Hors plan court.**

---

## 3. Trancher avant le code Phase 2–3

| Question | Options | Reco plan |
|----------|---------|-----------|
| Comment sonder la VM ? | SSH + `nvidia-smi` · agent léger · API monitoring | **SSH + nvidia-smi CSV** (simple, prouvable) |
| Qui crée le subnet ? | Déjà en console · script | Console d’abord (Phase 0) |
| Taille premier essai | 1× H100 · H200 | **1× H100** preset doc |
| Lien juges | Avant / après deadline | Pitch mock **inchangé** ; Compute = preuve perso ou add-on |

---

## 4. Coût & garde-fous

- Facturation **à la minute** → timer + delete obligatoire.
- `spawn_allowed=False` tant que `NGE_COMPUTE_SPAWN` unset.
- Solde AI Cloud : 25 $ (top-up 2026-10-03), budget 10 $/mois avec alertes. Le solde
  Token Factory (Nemotron, sandboxes) est un compte à part.
- Tarifs console (eu-north1, HT, relevés 2026-10-03) : H100 NVLink 4,50 $/h GPU,
  H200 5,40 $/h, L40S 1,35 $/h + 0,012 $/vCPU·h + 0,0032 $/Go·h. Premier essai
  Phase 2 recommandé sur **L40S** (~0,70 $ / 30 min) : la chaîne
  provision → `nvidia-smi` → delete se prouve aussi bien, et la L40S est
  datacenter-class (C9). H100 ensuite si on veut la photo.
- Image de boot : famille `ubuntu24.04-cuda13.0` (pilote NVIDIA → `nvidia-smi`) ;
  `ubuntu24.04-driverless` n'en a pas.
- VM préemptibles : moins chères, interruptibles, passent à la tarification *spot*
  le 2026-10-08 (bandeau console). Suffisant pour un probe de quelques minutes.
- GPU parfois indisponibles (« Not enough resources ») : vérifier la disponibilité
  (capacity advisor) avant la Phase 2.
- Aucun train AutoResearch / LINUS sur cette VM sans **Go** séparé.

---

## 5. Definition of Done (par phase)

| Phase | Done quand |
|-------|------------|
| 0 | `check_credentials()["ready_for_wire"] is True` |
| 1 | Script read-only liste platform/image OK — **fait** (`inventory`) |
| 2 | 1 run : provision → `nvidia-smi` → delete ; log `probe_kind=nvidia-smi` |
| 3 | 1 live hybride : pressure réelle → placement → remediation loguée |

---

## 6. Ce qu’on ne fait **pas** dans ce plan

- Spawn « pour voir » sans Go  
- Promettre aux juges que le heal live H100 est déjà là  
- Remplacer le film mock A2  
- Fusionner AutoResearch dans Compute dès le jour 1  

---

## 7. Prochain Go concret (à toi)

1. ~~**Go Phase 0**~~ — **fait 2026-10-03** (`ready_for_wire=True`)  
2. ~~**Go Phase 1**~~ — **fait 2026-10-03** (cible : L40S eu-north1)  
3. Puis **Go Phase 2** = phrase du type : *« Go spawn 1 H100 max 30 min »*

Sans Phase 0, tout le reste est du papier.
