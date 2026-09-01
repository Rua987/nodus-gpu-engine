#!/usr/bin/env python3
"""
🧠 COUCHE DE RAISONNEMENT SPINOZISTE (Intégrée dans l'Architecture)
==================================================================
Adapte le raisonnement DeepSeek directement dans le Transformer.
"""

import torch
import torch.nn as nn
import torch.nn.functional as F
from nodus_gpt import NodusGPTConfig, rms_norm

class SpinozistReasoningLayer(nn.Module):
    """
    LA COUCHE DE RAISONNEMENT : Génère le raisonnement interne <think>...</think>
    avant la réponse finale. C'est l'adaptation DeepSeek dans notre architecture.
    """
    def __init__(self, config: NodusGPTConfig):
        super().__init__()
        self.config = config
        # Couche pour détecter si on doit raisonner
        self.reasoning_gate = nn.Linear(config.n_embd, 1, bias=False)
        # Couche pour générer le raisonnement
        self.reasoning_mlp = nn.Sequential(
            nn.Linear(config.n_embd, 4 * config.n_embd, bias=False),
            nn.GELU(),
            nn.Linear(4 * config.n_embd, config.n_embd, bias=False)
        )
        # Couche pour générer la réponse finale après raisonnement
        self.answer_mlp = nn.Sequential(
            nn.Linear(config.n_embd * 2, 4 * config.n_embd, bias=False),  # *2 car on concatène raisonnement + contexte
            nn.GELU(),
            nn.Linear(4 * config.n_embd, config.n_embd, bias=False)
        )
    
    def forward(self, x, should_reason=False):
        """
        x: (B, T, C) - Les embeddings actuels
        should_reason: bool - Si True, on génère le raisonnement
        """
        B, T, C = x.size()
        
        if should_reason:
            # On génère le raisonnement pour chaque token
            reasoning = self.reasoning_mlp(x)  # (B, T, C)
            # On concatène le raisonnement avec le contexte original
            combined = torch.cat([x, reasoning], dim=-1)  # (B, T, 2*C)
            # On génère la réponse finale basée sur le raisonnement + contexte
            output = self.answer_mlp(combined)  # (B, T, C)
            return output, reasoning
        else:
            # Mode normal, pas de raisonnement
            return x, None

# SpinozistMoEBlockWithReasoning sera défini dans nodus_spinoza_moe_gpt_with_reasoning.py

def expliquer_architecture():
    print("""
🧠 ARCHITECTURE DE RAISONNEMENT INTÉGRÉE :
==========================================
1. SpinozistReasoningLayer : Génère le raisonnement interne
2. SpinozistMoEBlockWithReasoning : Bloc complet avec raisonnement optionnel
3. Le raisonnement peut être activé/désactivé selon le besoin

💡 Avantage : Le raisonnement est dans l'architecture, pas dans l'entraînement.
    """)

if __name__ == "__main__":
    expliquer_architecture()
    print("✅ Module de Raisonnement Spinoziste créé.")

