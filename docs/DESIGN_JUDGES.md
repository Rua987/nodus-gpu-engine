# Design (25 % de la note) — perso + capture

> « Design » Devpost = **le jury comprend en 5 s**. Pas un second app Streamlit.  
> La salle de contrôle **est** le HTML déjà émis par l’engine (`out/report_*.html`).

## Ce qu’on a corrigé vs le brief générique

| Brief (autre IA) | Chez nous |
|------------------|-----------|
| `nge run --mission "..."` | **N’existe pas.** Vrai : `python -m nge.demo_nebius --mock --watch --heuristic-plan` |
| KPI « coût GPU économisé ~$2.40 » | **Non mesuré** — on ne l’affiche pas |
| Dashboard Streamlit live | HTML **post-run** + terminal `--watch` pendant le run |
| Flotte toujours « simulée » | Mock = synthétique (film). Live = Contree **CPU**, heal gated |

## 5 secondes (ce que le HTML doit crier)

1. Hero : *Not a chatbot.*  
2. Cartes nœuds : temp / util / THROTTLED → MIGRATED.  
3. Story : pressure → placement → migrate → fix OK.  
4. KPI : `2/3` patches kept — honnête.

## Capture

```bash
cd packages/engine
python -m nge.demo_nebius --mock --watch --heuristic-plan
# ouvrir html:  — fond noir, cartes, timeline
```

Phrase : *Les autres montrent un agent qui répond. Nous montrons un système qui sent, place, migre, corrige et valide — visible en 5 secondes.*
