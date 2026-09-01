#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Source de plan NODUS local (pont PLAN).

Contrat : HANDOFF_PLAN_BRIDGE.md + bridge/plan_* .
- Prompt verbatim : bridge/plan_prompt.txt ({TASK})
- Sortie : JSON array de noms d'outils
- Parse : bridge/parse_plan.py (PAS nodus_planner.parse_plan)
- Confiance : label==valid uniquement ; sinon None → fallback cloud

Anti-RAM (8 Go / ~16 Go systeme) :
  NODUS_PLAN_SUBPROCESS=1 → charge le ckpt dans un enfant qui meurt apres
  le plan (la RAM revient vraiment au parent). Defaut: off (tests in-process) ;
  le harness met 1.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

_HERE = Path(__file__).resolve().parent
_BRIDGE = _HERE / "bridge"
# Checkpoint placé par l'utilisateur dans checkpoints/ (voir README) ; override : $env:NODUS_PLAN_CKPT
_DEFAULT_CKPT = str(_HERE / "checkpoints" / "checkpoint_sft_plan_v5.pt")
_EOT = 100257

# Cache process-wide (lazy) — uniquement mode in-process
_MODEL = None
_ENC = None
_DEVICE = None
_SEQ_LEN = 512
_PROMPT_TPL: Optional[str] = None
_PARSE_PLAN = None


def resolve_plan_device(cuda_available: Optional[bool] = None) -> str:
    """
    Choisit le device pour le planificateur NODUS local.

    Env `NODUS_PLAN_DEVICE` :
      - `cpu`  → force CPU (laisse la VRAM a Ollama / executeur)
      - `cuda` → force GPU si dispo, sinon CPU
      - `auto` ou unset → cuda si dispo, sinon cpu (comportement historique)

    Fonction pure si `cuda_available` est fourni ; sinon lit torch.

    Example:
        >>> resolve_plan_device(cuda_available=True)
        'cuda'
        >>> resolve_plan_device(cuda_available=False)
        'cpu'
    """
    raw = (os.environ.get("NODUS_PLAN_DEVICE") or "auto").strip().lower()
    if cuda_available is None:
        try:
            import torch
            cuda_available = bool(torch.cuda.is_available())
        except Exception:
            cuda_available = False
    if raw in ("cpu", "cpu_only", "host"):
        return "cpu"
    if raw in ("cuda", "gpu"):
        return "cuda" if cuda_available else "cpu"
    # auto / inconnu
    return "cuda" if cuda_available else "cpu"


def _load_parse_plan():
    global _PARSE_PLAN
    if _PARSE_PLAN is not None:
        return _PARSE_PLAN
    path = _BRIDGE / "parse_plan.py"
    spec = importlib.util.spec_from_file_location("bridge_parse_plan", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    _PARSE_PLAN = mod.parse_plan
    return _PARSE_PLAN


def _prompt_template() -> str:
    global _PROMPT_TPL
    if _PROMPT_TPL is not None:
        return _PROMPT_TPL
    path = _BRIDGE / "plan_prompt.txt"
    _PROMPT_TPL = path.read_text(encoding="utf-8")
    return _PROMPT_TPL


def build_nodus_plan_prompt(task: str) -> str:
    """Prompt pont PLAN — tache injectee verbatim ({TASK})."""
    return _prompt_template().replace("{TASK}", task)


def format_nodus_plan_suggestion(names: List[str]) -> str:
    """Bloc system soft : suggestion de noms d'outils (pas d'args)."""
    if not names:
        return ""
    numbered = "\n".join(
        f"{i}. Call tool `{n}` (you fill the arguments)"
        for i, n in enumerate(names, 1)
    )
    return (
        "\n\n## SUGGESTED TOOL SEQUENCE (local NODUS — verify each step)\n"
        "This is a SUGGESTION of tool names only. "
        "Verify each step fits the task. You MAY skip, reorder, or replace tools. "
        "YOU fill all arguments — do not invent tool names outside the allowed set:\n"
        f"{numbered}\n"
    )


def _install_checkpoint_compat() -> None:
    """Compatibilité checkpoint de release pré-renommage (linus_* → nodus_*).

    Un checkpoint produit avant le renommage peut contenir des références
    pickle aux anciens modules (linus_auto_model, linus_gpt, spinoza_gpt…) et
    aux anciennes classes (LinusAutoModel, LinusGPT…). On enregistre des alias
    sys.modules + alias de classes pour que torch.load() réussisse quelle que
    soit la provenance. Sans effet si le checkpoint ne référence aucun ancien
    nom (state_dict pur).
    """
    import sys

    aliases = {
        "linus_auto_model": "nodus_auto_model",
        "linus_gpt": "nodus_gpt",
        "spinoza_gpt": "nodus_spinoza_gpt",
        "spinoza_moe_gpt": "nodus_spinoza_moe_gpt",
        "spinozist_reasoning": "nodus_spinozist_reasoning",
    }
    for old, new in aliases.items():
        mod = sys.modules.get(new)
        if mod is None:
            try:
                mod = __import__(new, fromlist=["*"])
            except ImportError:
                continue
        sys.modules.setdefault(old, mod)
        for name in list(vars(mod)):
            if name.startswith("Nodus"):
                old_cls = "Linus" + name[len("Nodus"):]
                if not hasattr(mod, old_cls):
                    setattr(mod, old_cls, getattr(mod, name))


def _ensure_model(ckpt_path: Optional[str] = None):
    """Charge le checkpoint une fois (lazy). Raises si indisponible."""
    global _MODEL, _ENC, _DEVICE, _SEQ_LEN
    if _MODEL is not None:
        return _MODEL, _ENC, _DEVICE, _SEQ_LEN

    import tiktoken
    import torch

    from nodus_auto_model import NodusAutoConfig, NodusAutoModel

    path = ckpt_path or os.environ.get("NODUS_PLAN_CKPT", _DEFAULT_CKPT)
    if not Path(path).is_file():
        raise FileNotFoundError(f"plan checkpoint missing: {path}")

    device = resolve_plan_device()
    _install_checkpoint_compat()  # checkpoint release pré-renommage
    ckpt = torch.load(path, map_location="cpu", weights_only=False)
    cfg_d = ckpt.get("config", {})
    if isinstance(cfg_d, dict) and cfg_d:
        config = NodusAutoConfig(
            **{k: v for k, v in cfg_d.items() if hasattr(NodusAutoConfig, k)}
        )
    else:
        config = NodusAutoConfig()
    model = NodusAutoModel(config)
    model.load_state_dict(ckpt["model"])
    model.lm_head.weight = model.wte.weight
    model = model.to(device).eval()

    _MODEL = model
    _ENC = tiktoken.get_encoding("cl100k_base")
    _DEVICE = device
    _SEQ_LEN = min(512, int(getattr(config, "sequence_len", 512) or 512))
    return _MODEL, _ENC, _DEVICE, _SEQ_LEN


def _greedy_gen(model, enc, device, prompt: str, max_new: int = 80, seq_len: int = 512) -> str:
    import torch

    ids = enc.encode(prompt)
    x = torch.tensor([ids], dtype=torch.long, device=device)
    out = []
    with torch.no_grad():
        for _ in range(max_new):
            logits = model(x[:, -seq_len:])
            if isinstance(logits, tuple):
                logits = logits[0]
            nxt = int(logits[:, -1, :].argmax(dim=-1).item())
            if nxt == _EOT:
                break
            out.append(nxt)
            x = torch.cat([x, torch.tensor([[nxt]], device=device)], dim=1)
            text = enc.decode(out)
            if "[" in text and text.rstrip().endswith("]"):
                break
    return enc.decode(out)


def _subprocess_enabled() -> bool:
    raw = (os.environ.get("NODUS_PLAN_SUBPROCESS") or "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def _plog(msg: str, verbose: bool) -> None:
    """Logs plan → stderr (stdout reserve au JSON du worker --plan-once)."""
    if verbose:
        print(msg, file=sys.stderr, flush=True)


def _try_plan_tool_names_inprocess(
    task: str,
    ckpt_path: Optional[str] = None,
    verbose: bool = False,
) -> Optional[List[str]]:
    """Plan dans le process courant (garde le modele en cache)."""
    parse_plan = _load_parse_plan()
    try:
        model, enc, device, seq_len = _ensure_model(ckpt_path)
    except Exception as e:
        _plog(f"[plan-local] load failed: {e}", verbose)
        return None

    _plog(
        f"[plan-local] device={device} (NODUS_PLAN_DEVICE="
        f"{os.environ.get('NODUS_PLAN_DEVICE', 'auto')!r})",
        verbose,
    )

    prompt = build_nodus_plan_prompt(task)
    try:
        raw = _greedy_gen(model, enc, device, prompt, max_new=80, seq_len=seq_len)
    except Exception as e:
        _plog(f"[plan-local] generate failed: {e}", verbose)
        return None

    parsed = parse_plan(raw)
    _plog(f"[plan-local] raw={raw!r} -> {parsed}", verbose)
    if parsed.get("label") == "valid" and parsed.get("names"):
        return list(parsed["names"])
    return None

def _try_plan_tool_names_subprocess(
    task: str,
    ckpt_path: Optional[str] = None,
    verbose: bool = False,
    timeout_s: float = 180.0,
) -> Optional[List[str]]:
    """
    Plan dans un enfant Python qui charge NODUS puis **exit**.

    Le parent ne garde aucun poids — RAM vraiment liberee (preuve anti-rame).
    """
    env = os.environ.copy()
    # Enfant : toujours in-process (sinon recursion)
    env["NODUS_PLAN_SUBPROCESS"] = "0"
    cmd = [
        sys.executable,
        "-u",
        str(_HERE / "nodus_plan_local.py"),
        "--plan-once",
    ]
    if ckpt_path:
        cmd.extend(["--ckpt", ckpt_path])
    payload = (task or "").encode("utf-8")
    _plog("[plan-local] subprocess plan (child will exit after plan)", verbose)
    try:
        proc = subprocess.run(
            cmd,
            input=payload,
            capture_output=True,
            timeout=timeout_s,
            env=env,
            cwd=str(_HERE),
        )
    except subprocess.TimeoutExpired:
        _plog(f"[plan-local] subprocess timeout ({timeout_s}s)", verbose)
        return None
    except OSError as e:
        _plog(f"[plan-local] subprocess spawn failed: {e}", verbose)
        return None

    out = (proc.stdout or b"").decode("utf-8", errors="replace").strip()
    err = (proc.stderr or b"").decode("utf-8", errors="replace").strip()
    if verbose and err:
        for line in err.splitlines()[-8:]:
            print(line, file=sys.stderr, flush=True)
    if not out:
        _plog(
            f"[plan-local] subprocess empty stdout exit={proc.returncode}",
            verbose,
        )
        return None
    line = out.splitlines()[-1].strip()
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        _plog(f"[plan-local] subprocess bad json: {line[:200]!r}", verbose)
        return None
    if not data.get("ok"):
        _plog(f"[plan-local] subprocess fail: {data.get('error')}", verbose)
        return None
    names = data.get("names")
    if isinstance(names, list) and names:
        _plog(f"[plan-local] subprocess names={names}", verbose)
        return [str(n) for n in names]
    return None

def try_plan_tool_names(
    task: str,
    ckpt_path: Optional[str] = None,
    verbose: bool = False,
) -> Optional[List[str]]:
    """
    Genere un plan local. Retourne la liste de noms si label==valid, sinon None.

    None = le harnais doit fallback cloud (degraded/invalid/erreur chargement).

    Si NODUS_PLAN_SUBPROCESS=1 : enfant qui meurt apres le plan (anti-RAM).
    """
    if _subprocess_enabled():
        return _try_plan_tool_names_subprocess(task, ckpt_path=ckpt_path, verbose=verbose)
    return _try_plan_tool_names_inprocess(task, ckpt_path=ckpt_path, verbose=verbose)


def reset_plan_model_cache() -> None:
    """
    Decharge le planificateur NODUS (poids + cache CUDA).

    Utile sur 8 Go : liberer la VRAM avant que Ollama charge l'executeur,
    sinon concurrence NODUS+qwen → rame / extinction.
    """
    global _MODEL, _ENC, _DEVICE, _SEQ_LEN, _PROMPT_TPL, _PARSE_PLAN
    _MODEL = None
    _ENC = None
    _DEVICE = None
    _SEQ_LEN = 512
    _PROMPT_TPL = None
    _PARSE_PLAN = None
    try:
        import gc

        gc.collect()
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


def unload_plan_model_after_use(*, verbose: bool = False) -> None:
    """Unload si NODUS_PLAN_UNLOAD_AFTER n'est pas desactive (defaut: on)."""
    raw = (os.environ.get("NODUS_PLAN_UNLOAD_AFTER") or "1").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return
    reset_plan_model_cache()
    _plog("[plan-local] unloaded plan model (VRAM free for Ollama)", verbose)


def _plan_once_main(argv: List[str]) -> int:
    """Worker CLI : lit la tache sur stdin, ecrit une ligne JSON sur stdout, exit."""
    import argparse

    p = argparse.ArgumentParser(description="NODUS plan-once worker (exit after plan)")
    p.add_argument("--plan-once", action="store_true", required=True)
    p.add_argument("--ckpt", default=None)
    args = p.parse_args(argv)

    # Force in-process dans le worker
    os.environ["NODUS_PLAN_SUBPROCESS"] = "0"
    task = sys.stdin.read()
    names = _try_plan_tool_names_inprocess(task, ckpt_path=args.ckpt, verbose=True)
    if names:
        sys.stdout.write(json.dumps({"ok": True, "names": names}, ensure_ascii=False) + "\n")
        return 0
    sys.stdout.write(json.dumps({"ok": False, "error": "invalid_or_load_fail"}) + "\n")
    return 1


if __name__ == "__main__":
    if "--plan-once" in sys.argv:
        raise SystemExit(_plan_once_main(sys.argv[1:]))
    print("Usage: echo TASK | python nodus_plan_local.py --plan-once", file=sys.stderr)
    raise SystemExit(2)
