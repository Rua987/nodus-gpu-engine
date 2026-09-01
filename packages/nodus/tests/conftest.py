"""
conftest.py — Configuration pytest pour NODUS Swarm
=====================================================
Protège pytest contre les modules qui remplacent sys.stdout/stderr
au niveau module (pattern très répandu dans le projet).

Stratégie :
  • sys._called_from_test = True posé ICI au niveau MODULE (pas seulement
    dans pytest_configure) → flag actif AVANT que pytest 9 appelle
    importlib.import_module('nodus_nanochat') pendant la collection.
  • nodus_nanochat/__init__.py lit ce flag et court-circuite tous les
    imports coûteux (nodus_chat, nodus_gpt, PyTorch…).
"""
import sys

# ── Flag posé IMMÉDIATEMENT à l'import du conftest ───────────────────────────
# pytest charge conftest AVANT la collection, donc avant tout import package.
sys._called_from_test = True

# Sauvegarder les streams d'origine
_orig_stdout = sys.stdout
_orig_stderr = sys.stderr


def pytest_configure(config):
    """Appelé très tôt par pytest — s'assure que le flag est bien là."""
    sys._called_from_test = True  # redondant mais explicite


def pytest_unconfigure(config):
    """Restaurer stdout/stderr d'origine à la fin."""
    sys.stdout = _orig_stdout
    sys.stderr = _orig_stderr
    if hasattr(sys, "_called_from_test"):
        del sys._called_from_test
