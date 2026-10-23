# Try Nodus-GPU Engine in your browser

No install, no key, no network. Open a ready workspace:

**[Open in GitHub Codespaces](https://codespaces.new/Rua987/nodus-gpu-engine?quickstart=1)**
(free with any GitHub account; the engine is installed when the workspace opens, about a minute)

Then, in the workspace's terminal (it opens in `packages/engine`; the first line makes sure of it):

```bash
cd /workspaces/nodus-gpu-engine/packages/engine
python -m pytest -q                                                   # the test suite, about 30 s
python -m nge.demo_nebius --mock --watch --watch-delay 1.0 --heuristic-plan
python -m http.server 8000 --directory out                            # to read the report
```

1. The demo plays the whole loop on a simulated GPU fleet in under a minute: a node overheats and its work
   moves `nb-h100-02 → nb-h100-03`, then each failing test gets a patch that is kept only if the whole
   suite passes again. Expected: **2 of 3 failures fixed and verified** (the third has no canned patch,
   and the engine says so).
2. The last command serves the reports; a browser tab opens on port 8000 (or use the *Ports* tab).
   Click the newest `report_*.html` (the `.html`, not the `.md`): the control room of the run you just made.

## The real runs

The live path calls NVIDIA Nemotron on Nebius Token Factory and needs a Nebius key, so it is not part of
this test build. Its real runs are in the repository, each with its event log and a test that checks
every number we quote:

- the live run filmed for the video (5 of 6 bugs fixed, 5 of 5 pass hidden tests):
  `packages/engine/evidence/report_20261019T062658Z.md`
- the real migration on Nebius L40S GPUs (25.4 s → 20.5 s):
  `packages/engine/evidence/report_20261019T052247Z.md`

Demo video (2 min): https://youtu.be/g5iLfAx28KY

## On your own machine

Same commands after `git clone https://github.com/Rua987/nodus-gpu-engine` and
`pip install -r packages/engine/requirements.txt` (Python 3.10–3.12); open the printed `html:` path
directly instead of serving it.
