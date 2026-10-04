# Nebius Compute GPU — plan et résultats

> **Statut : Phases 0 à 3 faites.** Chaque VM a eu son **Go budget** explicite ; aucune sans.  
> Dernière écriture : **2026-10-04** (**Phases 0 à 3 vertes** : `nvidia-smi` réel sur une L40S, puis le heal
> en hybride sur 2 L40S — télémétrie réelle, rien migré à tort ; migration sur vraie pression : non démontrée).  
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

**Premier passage réel (2026-10-03, Go explicite « 1 L40S max 30 min ») — raté, instructif :**

| heure UTC | événement |
|---|---|
| 22:13:03 | création envoyée (id connu tout de suite) |
| 22:13:52 | VM `RUNNING`, IP publique |
| 22:13 → 22:43 | la sonde réessaie SSH en boucle, sans rien journaliser |
| 22:41:51 | SSH manuel, même clé : **`NVIDIA L40S, 23` °C** — le GPU est là |
| ~22:43 | le superviseur (limite de 30 min des tâches de fond) **tue** le processus à la minute même de son délai : le `finally` ne tourne pas |
| 22:49:25 | `cleanup` trouve la VM **encore `RUNNING`** et la supprime ; vérif indépendante : 0 instance, 0 disque, id `NOT_FOUND` |

VM vivante ~36 min au lieu de 30 au plus (~1 $ au lieu de ~0,77 $). Deux défauts :

1. **`\r\n` sous Windows.** Le script de sonde partait sur l'entrée standard en mode
   texte ; Python y transforme chaque `\n` en `\r\n`, et le `sh` d'Ubuntu lit
   `then\r` → erreur de syntaxe à chaque tentative (vérifié : `od -c` montre
   `a \r \n`). Le `sh` de Git sous Windows tolère les `\r`, ce qui le masquait en
   local. Corrigé : octets LF ; chaque échec SSH distinct est journalisé.
2. **La suppression ne dépendait que du processus.** Un `finally` ne protège pas
   d'un arrêt forcé. Ajouté : la VM **s'éteint d'elle-même** (`shutdown -h` via
   cloud-init) à `max_minutes + 5` ; `probe` **refuse de démarrer** si une VM
   étiquetée existe déjà. À l'usage : garder `--max-minutes` bien sous toute
   limite d'un superviseur.

Ce qui reste vrai : la chaîne compte de service → VM GPU → image CUDA →
`nvidia-smi` fonctionne (lecture manuelle). Ce qui n'est **pas** encore prouvé :
que `probe` lui-même ramène `probe_kind=nvidia-smi` et supprime la VM seul.

Tests : `tests/test_compute_probe.py` — fausse API, fausse horloge : suppression
après échec de création, SSH muet, VM jamais prête, Ctrl+C ; suppression
réessayée ; non-confirmation signalée ; plafond de durée ; refus de la CLI sans
les deux opt-in.

**Deuxième passage réel (2026-10-03, Go « 1 L40S max 15 min ») — réussi :**

| t | événement |
|---|---|
| 1,1 s | création envoyée |
| 38,6 s | VM créée ; 39,0 s `RUNNING`, IP publique |
| 47,3 s | `ssh_wait` journalisé : port 22 pas encore ouvert |
| 89,4 s | **`probe_kind=nvidia-smi`, NVIDIA L40S, 27 °C, 67,8 W, 45 Go, `gpu_class=datacenter`** |
| 192,1 s | **VM supprimée** (1re tentative) |

Vérifié ensuite, à part : 0 instance, 0 disque, id `NOT_FOUND`. ~3 min de VM
(~0,08 $ HT + disque et IP). Rapport, ids du compte retirés :
[`packages/engine/evidence/compute_probe_20261003T231022Z.json`](../packages/engine/evidence/compute_probe_20261003T231022Z.json)
(couvert par `tests/test_evidence.py`).

Ce que ça prouve : le moteur lui-même — pas un SSH manuel — crée une VM GPU
Nebius, en lit la télémétrie au format qu'il attend (`probe_kind=nvidia-smi`,
classe `datacenter`, donc les seuils datacenter de `telemetry.py` s'appliquent),
et la supprime seul. Ce que ça ne prouve pas : le heal sous vraie charge — une
seule lecture, GPU au repos (0 % d'utilisation), aucune migration. C'est la Phase 3.

### Phase 3 — Brancher heal live (archi A)
**But :** orchestrateur utilise Compute pour télémétrie/remediation ; shards restent Contree.

1. `NGE_FLEET_MODE=compute` + `NGE_SANDBOX=token_factory` (hybride)
2. Pressure → placement sur status **réels** → migrate = re-run shard (comme aujourd’hui)
3. ~~Preuve : event `gpu_remediation` avec `probe_kind=nvidia-smi`~~ — **revue, voir ci-dessous**
4. Film / HTML optionnel (perso ou juges selon timing)

**Ce que le plan ne voyait pas (2026-10-03, avant toute VM).** En archi A les
shards sont des pytest dans des sandboxes Token Factory ; la VM GPU ne fait que
rapporter sa télémétrie, et ne porte **aucun travail GPU**. Conséquences :

- **Migrations fantômes.** L'efficacité (travail utile par watt) y vaut 0 par
  construction. La vraie lecture de la Phase 2 (L40S, 27 °C, 0 %, 67,8 W) donnait
  santé `ok`, efficacité `0.0` < 0,25 : le heal aurait migré des shards hors de GPU
  sains — le bug déjà corrigé pour les sandboxes CPU, revenu par la porte des vraies
  métriques. **Corrigé** (`a68ece3`) : sur `nvidia-smi`, une efficacité basse ne
  comptait que si le scénario déclare `gpu_workload` ; sinon `gpu_efficiency_skipped`.
  Chaleur et puissance déclenchent toujours. *Revu le 2026-10-04 (Phase 4) : même
  avec `gpu_workload`, la lecture est prise après la fin du shard — notre travail GPU
  est fini, 0 ne mesure rien et désignerait justement les nœuds libres. Sur
  `nvidia-smi`, l'efficacité ne déclenche donc plus jamais ; c'est `busy` qui compte
  (voir Phase 4).*
- **Pas de vraie surchauffe à attendre.** 87 °C sur un GPU qui ne travaille pas ne
  viendra pas ; provoquer une surchauffe serait une mise en scène. La preuve visée
  devient donc : *le heal lit de la vraie télémétrie GPU et ne migre rien à tort*.
- Les seuils « datacenter » sont calés sur un H100 (700 W) ; une L40S plafonne vers
  350 W — la règle de puissance est donc prudente (jamais de fausse alerte), pas
  précise. Seuils par SKU : non faits.

**Code (2026-10-03)** — `nge/fleet/compute_fleet.py`, `ComputeGpuFleet` (plus un
squelette) : `provision` crée N VM étiquetées et s'éteignant seules, attend SSH ;
`status` = `nvidia-smi` par SSH, santé/efficacité selon la classe du GPU ; un
provision raté à mi-chemin supprime ce qu'il a créé ; `release` ne lève jamais et
liste ce qu'il n'a pas pu supprimer. Rien sans `NGE_COMPUTE_SPAWN=1`, refus si une
VM étiquetée traîne. `python -m nge.fleet.compute hybrid --i-know-cost` lance un
run d'orchestrateur flotte Compute + sandboxes Token Factory, **autofix coupé** :
chaque tentative de correctif réserve un nœud de flotte, ici une VM payante de plus
pour une vérification qui tourne en sandbox. 1 à 3 shards (= VM), 30 min max.
Tests : `tests/test_compute_fleet.py`, `tests/test_real_gpu_heal_gate.py`.

**Run live (Go « hybrid 2 L40S max 12 min », 2026-10-04 ~03:08–03:15 UTC)** —
`NGE_COMPUTE_SPAWN=1 python -m nge.fleet.compute hybrid --i-know-cost --shards 2 --max-minutes 12`,
code `251b6ad`. Rapport : [`evidence/report_20261004T031503Z.md`](../packages/engine/evidence/report_20261004T031503Z.md)
(+ `.html`), couvert par `tests/test_evidence.py`.

| t (s) | événement |
|---|---|
| 0 | `run_start` — flotte `compute`, sandbox `token_factory` |
| 192 | 2 VM L40S prêtes (SSH répond) : `cg-l40s-a-00`, `cg-l40s-a-01` |
| 214 / 231 | shard 0 / 1 fini ; `nvidia-smi` : L40S 25 °C, 36,5 / 35,1 W, 0 %, santé `ok`, efficacité 0.0 → `gpu_efficiency_skipped` ×2, 0 remediation |
| 231 | triage : 5 « échecs uniques », dont un faux (plus bas) ; autofix coupé par la mission |
| 439 | les 2 VM supprimées par le moteur (`gpu_release`) |

Après le run : 0 instance, 0 disque dans le projet (vérifié à part, en lecture
seule, avec le SA `phase2`). Coût : ≈ 6–7 min de VM ×2, soit ≈ 0,35 $ au tarif
L40S (disques et IP en sus), plus 2 appels Nemotron (0,0003 $).

Ce que ça prouve : le chemin hybride tourne de bout en bout. L'orchestrateur réserve
de vrais GPU Nebius, chaque décision de heal reçoit de la vraie télémétrie
`nvidia-smi`, une L40S au repos n'est pas prise pour un nœud inefficace (le correctif
`a68ece3` a joué deux fois, en vrai), et le moteur supprime ses VM. Ce que ça ne
prouve pas : une migration sur vraie pression. Il n'y en avait aucune, et on n'en a
pas fabriqué ; la règle chaleur/puissance sur vrai GPU n'est testée que hors réseau.

**Ce que le run a révélé : un nom de test coupé, compté comme un échec.** Le rapport
liste `test_nodus_grafana.py::test_connect_mc`, un test qui n'existe pas. ContreeSDK
coupe stdout à 65 535 octets par défaut ; la sortie `-v` du shard 0 en faisait
≈ 65 600 : la dernière ligne `FAILED` a été coupée au milieu du nom, et le vrai
`test_connect_mcp_forwards_org_id_env` n'a jamais été vu. Rejoué en sandbox Token
Factory (sans VM) aux deux limites :
[`evidence/output_cut_replay_20261004.txt`](../packages/engine/evidence/output_cut_replay_20261004.txt),
`python -m bench.output_cut_replay --i-know-cost`. **Corrigé** : le moteur demande
4 MiB (`NGE_CONTREE_OUTPUT_BYTES`) et lit le drapeau `truncated` du SDK ; s'il est
levé, la dernière ligne (le fragment) est ignorée, l'événement
`shard_output_truncated` et le rapport le disent, et une vérification de correctif
dont la sortie est coupée n'est jamais `verified` — une régression au-delà de la
coupe serait invisible. Tests : `tests/test_output_truncation.py`. Les preuves
antérieures ne sont pas touchées : dans les 41 autres rapports de `evidence/`, chaque
nom de test en échec existe dans le code.

### Phase 4 — Exec sur Compute : une vraie migration, sous charge **induite et déclarée**

*Construit le 2026-10-04, testé sans réseau, **pas encore lancé** (Go € à venir).*

Pourquoi : en Phase 3 aucun GPU ne travaillait, donc aucune pression réelle ne pouvait
exister, et provoquer une surchauffe aurait été une mise en scène. Ici, la charge est
provoquée **et dite** : le rapport l'annonce comme induite, jamais comme spontanée.

- **Des shards qui utilisent le GPU.** `bench/gpubench` : un produit matriciel CUDA
  (`matmul.cu`, 4096², vérifié sur 16 entrées recalculées en double sur CPU), compilé
  avec le `nvcc` de l'image (`ubuntu24.04-cuda13.0` embarque le CUDA Toolkit 13.0).
  Deux fichiers de test identiques, un par shard : le shard du nœud chargé et celui du
  nœud libre chronomètrent le même travail.
- **Exécutés sur la VM.** Sandbox `compute` (`nge/sandbox/compute.py`) : un répertoire
  sur la VM du nœud, fichiers envoyés en tar.gz dans le script SSH, venv (pytest)
  installé par cloud-init, `nvcc` sur le PATH. La commande passe toujours par le jail.
  Une VM n'est « prête » qu'une fois le venv en place ; un cloud-init en erreur arrête
  l'attente au lieu de facturer la VM jusqu'à l'échéance.
- **La charge induite.** `nge/fleet/gpu_burn.cu` : une boucle FMA sur tous les SM
  pendant N s, puis sortie seule ; compilée sur la VM, détachée de SSH. Le scénario
  (`scenarios/gpu_contention.json`) la déclare (`induce_gpu_load`) ; l'événement
  `gpu_load_induced` (`declared: true`) l'écrit dans le journal, la console et le
  rapport (« induced load (declared, not organic) »).
- **La règle `busy`.** Une VM est lue après la fin du shard : l'utilisation encore
  présente appartient à un autre processus. Avec `gpu_workload`, ≥ 90 % = `busy` →
  pression → placement → migration. La lecture liste les processus présents sur le
  GPU (`nvidia-smi --query-compute-apps`) : la preuve de *qui* occupe le nœud.
- **La mesure.** La remédiation garde les deux durées du même shard : sur le nœud
  quitté et sur le nouveau (`duration_before_s` / `duration_after_s`).

Commande (garde-fous de `hybrid` ; au plus 3 VM — 2 shards + le remplacement) :
`NGE_COMPUTE_SPAWN=1 python -m nge.fleet.compute contention --i-know-cost --max-minutes 20`.
Coût estimé : ~30 min-VM L40S au total, ≈ 0,8 $ (plafond 3 × 20 min ≈ 1,6 $), disques et
IP en sus.

Ce que ça prouvera, si le run passe : la boucle voit une vraie contention sur de vraies
métriques, migre, et le gain se mesure. Ce que ça ne prouvera pas : une surchauffe ou une
panne spontanée ; la charge est la nôtre, et le rapport le dit. Tests :
`tests/test_gpu_contention.py`, `tests/test_real_gpu_heal_gate.py`.

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
| 2 | 1 run : provision → `nvidia-smi` → delete ; log `probe_kind=nvidia-smi` — **fait 2026-10-03** (L40S, 192 s) |
| 3 | 1 live hybride : télémétrie réelle → décision de heal, rien migré à tort, VM supprimées — **fait 2026-10-04** (2 L40S). Migration sur vraie pression : non démontrée (aucune pression réelle) |

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
3. ~~**Go Phase 2**~~ — **fait 2026-10-03** (L40S ; 1er essai raté puis corrigé, 2e réussi)
4. ~~**Phase 3**~~ — **fait 2026-10-04** (2 L40S, rien migré à tort ; a révélé la coupe de sortie ContreeSDK, corrigée)
5. **Phase 4** (contention induite et déclarée) — construite et testée sans réseau ; **Go € requis** pour le run

Sans Phase 0, tout le reste est du papier.
