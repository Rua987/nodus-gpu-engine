#!/usr/bin/env python3
"""
🚀 NODUS MoE V10 - LE CERVEAU COLLECTIF SPINOZISTE
==================================================
Cette architecture implémente une Mixture of Experts (MoE) 
où chaque expert est un Sage spécialisé, supervisé par la Libertématique.
"""

import math
import torch
import torch.nn as nn
import torch.nn.functional as F
from dataclasses import dataclass
from typing import Optional, Tuple, List

from nodus_gpt import NodusGPTConfig, rms_norm, apply_rotary_embedding, precompute_rotary_embeddings
from nodus_spinoza_gpt import SpinozistAttention

class SpinozistExpert(nn.Module):
    """
    Un Expert spécialisé (MLP). C'est un 'organe' du cerveau collectif.
    """
    def __init__(self, config: NodusGPTConfig):
        super().__init__()
        self.c_fc = nn.Linear(config.n_embd, 4 * config.n_embd, bias=False)
        self.c_proj = nn.Linear(4 * config.n_embd, config.n_embd, bias=False)
        self.dropout = nn.Dropout(config.dropout)

    def forward(self, x):
        x = self.c_fc(x)
        x = F.gelu(x)
        x = self.c_proj(x)
        x = self.dropout(x)
        return x

class SpinozistRouter(nn.Module):
    """
    LE ROUTER SACRÉ : Décide quel expert possède la plus grande 'Puissance d'Agir' (Conatus)
    pour traiter le token actuel.
    """
    def __init__(self, n_embd: int, n_experts: int):
        super().__init__()
        self.gate = nn.Linear(n_embd, n_experts, bias=False)

    def forward(self, x):
        # On calcule les scores de désir (logits) pour chaque expert
        logits = self.gate(x) # (B, T, n_experts)
        # On utilise une logique de Top-K (ici Top-1 ou Top-2)
        # Pour NODUS, on commence par Top-1 pour la simplicité
        probs = F.softmax(logits, dim=-1)
        return probs

class SpinozistMoELayer(nn.Module):
    """
    La couche MoE qui fusionne les experts.
    Supporte maintenant un 'Override Sémantique' (Fonction de Pilotage).
    """
    def __init__(self, config: NodusGPTConfig, n_experts: int = 4):
        super().__init__()
        self.n_experts = n_experts
        self.experts = nn.ModuleList([SpinozistExpert(config) for _ in range(n_experts)])
        self.router = SpinozistRouter(config.n_embd, n_experts)

    def forward(self, x, domain_mask=None):
        B, T, C = x.size()
        x_flat = x.view(-1, C) # (B*T, C)
        
        # 1. Obtenir les probabilités de base du router
        router_probs = self.router(x_flat) # (B*T, n_experts)
        
        # 2. 💉 INJECTION DE LA FONCTION SÉMANTIQUE (Ton idée !)
        # Si on a un masque de domaine, on écrase l'ontologie apprise
        if domain_mask is not None:
            domain_mask_tensor = domain_mask.to(x.device)
            
            # Si un seul expert est force (masque binaire), FORCER cet expert
            if (domain_mask_tensor > 0).sum() == 1:
                # Un seul expert active : FORCER cet expert a 100%
                expert_idx = domain_mask_tensor.argmax().item()
                router_probs = torch.zeros_like(router_probs)
                router_probs[:, expert_idx] = 1.0
            else:
                # Plusieurs experts actifs : multiplier et normaliser
                router_probs = router_probs * domain_mask_tensor
                # Normaliser pour que la somme fasse toujours 1
                router_probs = router_probs / (router_probs.sum(dim=-1, keepdim=True) + 1e-9)
        
        # 3. Sélectionner l'expert dominant (Top-1)
        expert_weights, expert_indices = torch.topk(router_probs, k=1, dim=-1)
        
        final_output = torch.zeros_like(x_flat)
        
        # 4. Router chaque token vers son expert
        for i in range(self.n_experts):
            mask = (expert_indices == i).any(dim=-1)
            if mask.any():
                expert_input = x_flat[mask]
                expert_output = self.experts[i](expert_input)
                final_output[mask] = expert_output * expert_weights[mask]
                
        return final_output.view(B, T, C)

class SpinozistMoEBlock(nn.Module):
    """
    Un bloc complet associant Attention Sacrée et Experts MoE.
    """
    def __init__(self, config: NodusGPTConfig, n_experts: int = 4):
        super().__init__()
        self.attn = SpinozistAttention(config)
        self.moe = SpinozistMoELayer(config, n_experts=n_experts)
    
    def forward(self, x, cos, sin, domain_mask=None):
        # Attention (L'Âme qui perçoit)
        x = x + self.attn(rms_norm(x), cos, sin)
        # MoE (Le Corps qui agit via ses experts)
        # Injection du domain_mask ici !
        x = x + self.moe(rms_norm(x), domain_mask=domain_mask)
        return x

class SpinozistMoEGPT(nn.Module):
    def __init__(self, config: NodusGPTConfig, n_experts: int = 4):
        super().__init__()
        self.config = config
        self.wte = nn.Embedding(config.vocab_size, config.n_embd)
        self.blocks = nn.ModuleList([SpinozistMoEBlock(config, n_experts=n_experts) for _ in range(config.n_layer)])
        self.lm_head = nn.Linear(config.n_embd, config.vocab_size, bias=False)
        
        self.register_buffer("cos", torch.zeros(1, config.sequence_len, 1, config.head_dim // 2))
        self.register_buffer("sin", torch.zeros(1, config.sequence_len, 1, config.head_dim // 2))
        
        cos, sin = precompute_rotary_embeddings(config.sequence_len, config.head_dim)
        self.cos = cos
        self.sin = sin
        
        try:
            print(f"🏛️ NODUS MoE V10 Initialisé ({n_experts} Experts spécialisés) 🏛️")
        except (ValueError, OSError):
            pass  # stdout fermé, ignorer

    def forward(self, idx, targets=None, domain_mask=None):
        B, T = idx.size()
        cos = self.cos[:, :T].to(idx.device)
        sin = self.sin[:, :T].to(idx.device)
        
        x = self.wte(idx)
        x = rms_norm(x)
        
        for block in self.blocks:
            # On passe le domain_mask à chaque bloc MoE
            x = block(x, cos, sin, domain_mask=domain_mask)
            
        x = rms_norm(x)
        logits = self.lm_head(x)
        
        if targets is not None:
            loss = F.cross_entropy(logits.reshape(-1, logits.size(-1)), targets.reshape(-1), ignore_index=-1)
            return loss
        
        return logits

    @torch.inference_mode()
    def generate(self, idx, max_new_tokens, temperature=1.0, top_k=None, domain_mask=None, logit_bias=None):
        for _ in range(max_new_tokens):
            idx_cond = idx[:, -self.config.sequence_len:]
            # On passe le domain_mask à chaque étape de génération !
            logits = self.forward(idx_cond, domain_mask=domain_mask)
            logits = logits[:, -1, :] / temperature
            
            # 🆕 Application du Bâillon Sémantique (Logit Bias)
            if logit_bias is not None:
                # logit_bias est un tenseur de la taille du vocab avec des -inf sur les mots interdits
                logits = logits + logit_bias.to(idx.device)
            
            if top_k is not None:
                v, _ = torch.topk(logits, min(top_k, logits.size(-1)))
                logits[logits < v[:, [-1]]] = float('-inf')
            probs = F.softmax(logits, dim=-1)
            next_token = torch.multinomial(probs, num_samples=1)
            idx = torch.cat([idx, next_token], dim=1)
            yield next_token.item()

if __name__ == "__main__":
    # Test de validation MoE
    config = NodusGPTConfig(vocab_size=1000, n_layer=2, n_head=4, n_embd=128)
    model = SpinozistMoEGPT(config, n_experts=4)
    x = torch.randint(0, 1000, (1, 10))
    logits = model(x)
    print(f"✅ MoE Test réussi. Logits shape: {logits.shape}")
    print(f"🚀 Architecture: 2 couches, 4 experts par couche.")

