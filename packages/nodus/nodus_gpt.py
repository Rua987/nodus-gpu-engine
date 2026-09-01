#!/usr/bin/env python3
"""
🏛️ NODUS NanoGPT - Notre propre modèle GPT from scratch !
============================================================
Inspiré de nanochat de Karpathy, mais simplifié pour apprendre.

🎯 ANALOGIE POUR COMPRENDRE :
-----------------------------
Imagine que le GPT est comme un **cuisinier** qui prépare des phrases :

1. **Embedding** = Le dictionnaire des ingrédients
   - Chaque mot a une "saveur" numérique unique (un vecteur)

2. **Attention** = Le cuisinier qui regarde tous les ingrédients
   - "Hmm, si j'ai 'Le chat', le prochain mot doit être..."
   - Il regarde les mots précédents pour deviner le suivant

3. **MLP** = La sauce secrète
   - Transforme et enrichit les saveurs

4. **LM Head** = Le plat final
   - Choisit le prochain mot parmi tous les mots possibles

📚 CONCEPTS CLÉS (Style Karpathy) :
-----------------------------------
- RMSNorm : Normalisation simple (pas de biais)
- RoPE : Position relative par rotation (pas d'embedding de position)
- Attention Causale : Ne regarde que le passé
- ReLU² : Activation carrée pour plus d'expressivité

🔥 ARCHITECTURE :
-----------------
Input → Embedding → [Block × N] → LM Head → Output

Où chaque Block = Attention + MLP

Auteur: Temple IAM (style Karpathy fonctionnel pur)
"""

import math
from dataclasses import dataclass
from typing import Optional, Tuple, Generator
import torch
import torch.nn as nn
import torch.nn.functional as F


# ==============================================================================
# 📐 CONFIGURATION DU MODÈLE
# ==============================================================================
# Imagine ça comme la "recette" de notre modèle

@dataclass
class NodusGPTConfig:
    """
    Configuration du modèle - Les paramètres de notre "recette"
    
    🎯 Analogie: C'est comme choisir la taille de ta pizza :
    - sequence_len = Combien de mots on peut lire d'un coup
    - vocab_size = Combien de mots différents on connaît
    - n_layer = Combien de couches (comme les étages d'un immeuble)
    - n_head = Combien de "regards" différents en parallèle
    - n_embd = La richesse de notre représentation
    """
    # Taille de la séquence (contexte)
    sequence_len: int = 1024  # GIGA-CERVEAU: Augmenté de 256 à 1024
    
    # RoPE Scaling (Interpolation pour contexte étendu)
    rope_scaling: float = 4.0  # 1024 / 256 = 4.0
    
    # Taille du vocabulaire (combien de tokens différents)
    vocab_size: int = 50304  # Même que GPT-4 tokenizer
    
    # Nombre de couches Transformer
    n_layer: int = 4  # Plus petit (Karpathy: 12) pour entraînement rapide
    
    # Nombre de têtes d'attention
    n_head: int = 4  # Plus petit (Karpathy: 6)
    
    # Dimension des embeddings
    n_embd: int = 256  # Plus petit (Karpathy: 768)
    
    # Dropout (régularisation)
    dropout: float = 0.1
    
    @property
    def head_dim(self) -> int:
        """Dimension de chaque tête = n_embd / n_head"""
        return self.n_embd // self.n_head
    
    def count_params_millions(self) -> float:
        """Estime le nombre de paramètres en millions"""
        # Embedding + Attention + MLP + LM Head
        embd = self.vocab_size * self.n_embd
        attn = 4 * self.n_embd * self.n_embd * self.n_layer  # Q, K, V, proj
        mlp = 8 * self.n_embd * self.n_embd * self.n_layer   # fc + proj
        head = self.vocab_size * self.n_embd
        return (embd + attn + mlp + head) / 1_000_000


# ==============================================================================
# 🔧 FONCTIONS PURES (Style Karpathy - pas d'effets de bord)
# ==============================================================================

def rms_norm(x: torch.Tensor, eps: float = 1e-6) -> torch.Tensor:
    """
    RMSNorm - Normalisation sans paramètres apprenables
    
    🎯 Analogie: C'est comme ajuster le volume d'une chanson
    - Trop fort ? On baisse
    - Trop faible ? On augmente
    - Objectif: Un volume "normal" (variance = 1)
    
    Formule: x / sqrt(mean(x²) + eps)
    
    Args:
        x: Tenseur d'entrée
        eps: Petit nombre pour éviter division par zéro
    
    Returns:
        Tenseur normalisé
    """
    # Calcule la moyenne des carrés sur la dernière dimension
    variance = x.pow(2).mean(dim=-1, keepdim=True)
    # Normalise
    return x * torch.rsqrt(variance + eps)


def apply_rotary_embedding(
    x: torch.Tensor,
    cos: torch.Tensor,
    sin: torch.Tensor
) -> torch.Tensor:
    """
    RoPE - Rotary Position Embedding
    
    🎯 Analogie: Imagine une horloge :
    - Chaque position dans la phrase = une heure différente
    - On "tourne" les vecteurs selon leur position
    - Position 1 = tourné un peu, Position 10 = tourné beaucoup
    
    Avantage: La distance relative entre mots est encodée naturellement !
    
    Args:
        x: Tenseur (batch, seq_len, n_head, head_dim)
        cos, sin: Matrices de rotation pré-calculées
    
    Returns:
        Tenseur avec position encodée
    """
    # Sépare la dimension en deux moitiés
    d = x.shape[-1] // 2
    x1, x2 = x[..., :d], x[..., d:]
    
    # Applique la rotation (comme une multiplication de nombres complexes)
    y1 = x1 * cos + x2 * sin
    y2 = x1 * (-sin) + x2 * cos
    
    return torch.cat([y1, y2], dim=-1)


def precompute_rotary_embeddings(
    seq_len: int,
    head_dim: int,
    device: torch.device = None,
    base: float = 10000.0,
    scaling_factor: float = 1.0  # GIGA-PATCH: Pour étendre le contexte
) -> Tuple[torch.Tensor, torch.Tensor]:
    """
    Pré-calcule les embeddings rotatifs pour toutes les positions
    
    🎯 Analogie: C'est comme pré-calculer tous les angles d'horloge
    avant de les utiliser. Plus efficace !
    
    Args:
        seq_len: Longueur maximale de séquence
        head_dim: Dimension de chaque tête
        device: CPU ou GPU
        base: Fréquence de base (10000 comme dans le papier original)
        scaling_factor: Facteur d'interpolation (ex: 4.0 pour passer de 256 à 1024)
    
    Returns:
        (cos, sin) pré-calculés
    """
    # Crée les fréquences pour chaque dimension
    channel_range = torch.arange(0, head_dim, 2, dtype=torch.float32, device=device)
    inv_freq = 1.0 / (base ** (channel_range / head_dim))
    
    # Crée les positions (avec scaling pour interpolation)
    positions = torch.arange(seq_len, dtype=torch.float32, device=device) / scaling_factor
    
    # Calcule les angles (position × fréquence)
    angles = torch.outer(positions, inv_freq)
    
    # Calcule cos et sin
    cos = angles.cos()
    sin = angles.sin()
    
    # Ajoute les dimensions batch et head pour broadcasting
    cos = cos[None, :, None, :]  # (1, seq_len, 1, head_dim/2)
    sin = sin[None, :, None, :]
    
    return cos, sin


# ==============================================================================
# 🧠 ATTENTION CAUSALE (Le cœur du Transformer)
# ==============================================================================

class NodusCausalAttention(nn.Module):
    """
    Attention Causale - Le "regard" du modèle
    
    🎯 Analogie du Restaurant :
    Imagine un serveur qui note les commandes :
    - Il peut regarder les commandes PASSÉES (causale)
    - Mais PAS les commandes FUTURES (ce serait de la triche !)
    - Multi-head = Plusieurs serveurs en parallèle
    
    Fonctionnement :
    1. Query (Q) = "Que cherche ce mot ?"
    2. Key (K) = "Qu'est-ce que ce mot offre ?"
    3. Value (V) = "Quelle est la valeur de ce mot ?"
    4. Score = Q · K (compatibilité)
    5. Attention = softmax(Score) · V (moyenne pondérée)
    """
    
    def __init__(self, config: NodusGPTConfig):
        super().__init__()
        self.config = config
        
        # Projections linéaires pour Q, K, V (sans biais, style Karpathy)
        self.c_q = nn.Linear(config.n_embd, config.n_embd, bias=False)
        self.c_k = nn.Linear(config.n_embd, config.n_embd, bias=False)
        self.c_v = nn.Linear(config.n_embd, config.n_embd, bias=False)
        
        # Projection de sortie
        self.c_proj = nn.Linear(config.n_embd, config.n_embd, bias=False)
        
        # Dropout pour régularisation
        self.dropout = nn.Dropout(config.dropout)
    
    def forward(
        self,
        x: torch.Tensor,
        cos: torch.Tensor,
        sin: torch.Tensor
    ) -> torch.Tensor:
        """
        Forward pass de l'attention
        
        Args:
            x: Input (batch, seq_len, n_embd)
            cos, sin: Embeddings rotatifs
        
        Returns:
            Output (batch, seq_len, n_embd)
        """
        B, T, C = x.size()
        config = self.config
        
        # 1. Projette vers Q, K, V et reshape pour multi-head
        q = self.c_q(x).view(B, T, config.n_head, config.head_dim)
        k = self.c_k(x).view(B, T, config.n_head, config.head_dim)
        v = self.c_v(x).view(B, T, config.n_head, config.head_dim)
        
        # 2. Applique RoPE (encodage de position)
        q = apply_rotary_embedding(q, cos, sin)
        k = apply_rotary_embedding(k, cos, sin)
        
        # 3. QK Norm (stabilisation, style Karpathy)
        q = rms_norm(q)
        k = rms_norm(k)
        
        # 4. Transpose pour avoir (B, n_head, T, head_dim)
        q = q.transpose(1, 2)
        k = k.transpose(1, 2)
        v = v.transpose(1, 2)
        
        # 5. Attention avec Flash Attention (PyTorch 2.0+)
        # is_causal=True = Ne regarde que le passé !
        y = F.scaled_dot_product_attention(q, k, v, is_causal=True)
        
        # 6. Recombine les têtes
        y = y.transpose(1, 2).contiguous().view(B, T, C)
        
        # 7. Projection de sortie + dropout
        y = self.dropout(self.c_proj(y))
        
        return y


# ==============================================================================
# 🍳 MLP (La "sauce secrète")
# ==============================================================================

class NodusMLP(nn.Module):
    """
    Multi-Layer Perceptron - Transformation non-linéaire
    
    🎯 Analogie de la Cuisine :
    L'attention combine les ingrédients, mais le MLP les "cuit" :
    - Entrée → Expansion (×4) → ReLU² → Réduction
    
    ReLU² (ReLU au carré) :
    - Plus expressif que ReLU simple
    - f(x) = max(0, x)² 
    - Utilisé dans les modèles récents (Karpathy, Llama)
    """
    
    def __init__(self, config: NodusGPTConfig):
        super().__init__()
        
        # Expansion × 4 (standard dans Transformers)
        hidden_dim = 4 * config.n_embd
        
        # Couches linéaires (sans biais)
        self.c_fc = nn.Linear(config.n_embd, hidden_dim, bias=False)
        self.c_proj = nn.Linear(hidden_dim, config.n_embd, bias=False)
        
        # Dropout
        self.dropout = nn.Dropout(config.dropout)
    
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Forward pass du MLP
        
        ReLU² = max(0, x)² - Plus expressif que ReLU classique
        """
        x = self.c_fc(x)
        x = F.relu(x).square()  # ReLU² activation
        x = self.dropout(self.c_proj(x))
        return x


# ==============================================================================
# 🧱 BLOCK TRANSFORMER (Attention + MLP)
# ==============================================================================

class NodusBlock(nn.Module):
    """
    Un bloc Transformer = Attention + MLP
    
    🎯 Analogie de l'Immeuble :
    Chaque étage (block) fait deux choses :
    1. Attention = Les gens se parlent entre eux
    2. MLP = Chacun réfléchit individuellement
    
    Avec des "escaliers de secours" (résidual connections) :
    output = input + transformation
    → Si la transformation rate, l'input passe quand même !
    """
    
    def __init__(self, config: NodusGPTConfig):
        super().__init__()
        self.attn = NodusCausalAttention(config)
        self.mlp = NodusMLP(config)
    
    def forward(
        self,
        x: torch.Tensor,
        cos: torch.Tensor,
        sin: torch.Tensor
    ) -> torch.Tensor:
        """
        Pre-norm architecture (comme GPT-2, Llama, etc.)
        
        x → norm → attn → + → norm → mlp → +
        └──────────────────┘   └──────────────┘
             résiduel              résiduel
        """
        # Attention avec connexion résiduelle
        x = x + self.attn(rms_norm(x), cos, sin)
        # MLP avec connexion résiduelle
        x = x + self.mlp(rms_norm(x))
        return x


# ==============================================================================
# 🏛️ NODUS GPT - Le Modèle Complet
# ==============================================================================

class NodusGPT(nn.Module):
    """
    🏛️ NODUS GPT - Notre propre modèle de langage !
    
    🎯 Vue d'ensemble (analogie de l'école) :
    
    1. ENTRÉE : Les mots arrivent (tokens)
    2. EMBEDDING : Chaque mot reçoit un "badge" numérique
    3. BLOCS : Les élèves discutent et réfléchissent (× n_layer)
    4. SORTIE : On vote pour le prochain mot
    
    Architecture :
    ┌─────────────────────────────────────────┐
    │  Token IDs                              │
    │       ↓                                 │
    │  [Embedding] ─────→ (B, T, n_embd)      │
    │       ↓                                 │
    │  [RMSNorm]                              │
    │       ↓                                 │
    │  ┌─────────┐                            │
    │  │ Block 1 │ ← Attention + MLP          │
    │  └────┬────┘                            │
    │       ↓                                 │
    │  ┌─────────┐                            │
    │  │ Block 2 │                            │
    │  └────┬────┘                            │
    │       ↓                                 │
    │     ...                                 │
    │       ↓                                 │
    │  ┌─────────┐                            │
    │  │ Block N │                            │
    │  └────┬────┘                            │
    │       ↓                                 │
    │  [RMSNorm]                              │
    │       ↓                                 │
    │  [LM Head] ─────→ (B, T, vocab_size)    │
    │       ↓                                 │
    │  Logits (scores pour chaque mot)        │
    └─────────────────────────────────────────┘
    """
    
    def __init__(self, config: NodusGPTConfig):
        super().__init__()
        self.config = config
        
        # 1. Embedding des tokens
        # Chaque token → un vecteur de dimension n_embd
        self.wte = nn.Embedding(config.vocab_size, config.n_embd)
        
        # 2. Stack de blocs Transformer
        self.blocks = nn.ModuleList([
            NodusBlock(config) for _ in range(config.n_layer)
        ])
        
        # 3. LM Head - Projette vers le vocabulaire
        self.lm_head = nn.Linear(config.n_embd, config.vocab_size, bias=False)
        
        # 4. Pré-calcul des embeddings rotatifs
        self.register_buffer(
            "cos",
            torch.zeros(1, config.sequence_len, 1, config.head_dim // 2)
        )
        self.register_buffer(
            "sin",
            torch.zeros(1, config.sequence_len, 1, config.head_dim // 2)
        )
        
        # Initialise les poids
        self._init_weights()
        
        # Affiche les stats
        n_params = sum(p.numel() for p in self.parameters())
        print(f"NodusGPT initialized!")
        print(f"   Parameters: {n_params:,} ({n_params/1e6:.2f}M)")
        print(f"   Config: {config.n_layer}L x {config.n_head}H x {config.n_embd}D")
    
    def _init_weights(self):
        """
        Initialisation des poids (style Karpathy)
        
        - Embeddings: Normal(0, 1)
        - LM Head: Normal(0, 0.001) - très petit !
        - Linéaires: Uniform pour éviter les outliers
        - Projections: Zeros (résiduel = identity au début)
        """
        # Token embedding
        nn.init.normal_(self.wte.weight, mean=0.0, std=1.0)
        
        # LM Head - très petit pour commencer "neutre"
        nn.init.normal_(self.lm_head.weight, mean=0.0, std=0.001)
        
        # Blocs
        for block in self.blocks:
            # Attention - Uniform pour stabilité
            s = (3 ** 0.5) * (self.config.n_embd ** -0.5)
            nn.init.uniform_(block.attn.c_q.weight, -s, s)
            nn.init.uniform_(block.attn.c_k.weight, -s, s)
            nn.init.uniform_(block.attn.c_v.weight, -s, s)
            nn.init.zeros_(block.attn.c_proj.weight)  # Résiduel = 0 au début
            
            # MLP
            nn.init.uniform_(block.mlp.c_fc.weight, -s, s)
            nn.init.zeros_(block.mlp.c_proj.weight)  # Résiduel = 0 au début
        
        # Rotary embeddings
        cos, sin = precompute_rotary_embeddings(
            self.config.sequence_len,
            self.config.head_dim,
            device=self.wte.weight.device,
            scaling_factor=self.config.rope_scaling # GIGA-PATCH
        )
        self.cos = cos
        self.sin = sin
    
    def forward(
        self,
        idx: torch.Tensor,
        targets: Optional[torch.Tensor] = None
    ) -> torch.Tensor:
        """
        Forward pass du modèle
        
        Args:
            idx: Token IDs (batch, seq_len)
            targets: Labels pour le calcul de la loss (optionnel)
        
        Returns:
            Si targets: Loss (scalar)
            Sinon: Logits (batch, seq_len, vocab_size)
        """
        B, T = idx.size()
        device = idx.device
        
        # Vérifie que la séquence n'est pas trop longue
        # GIGA-PATCH: On accepte maintenant 1024
        assert T <= self.config.sequence_len, \
            f"Séquence trop longue ! {T} > {self.config.sequence_len}"
        
        # Assure que RoPE est sur le bon device et à la bonne taille
        if self.cos.device != device or self.cos.size(1) < T:
            cos, sin = precompute_rotary_embeddings(
                max(T, self.config.sequence_len),
                self.config.head_dim,
                device=device,
                scaling_factor=self.config.rope_scaling # GIGA-PATCH
            )
            self.cos = cos.to(device)
            self.sin = sin.to(device)
        
        # Tronque RoPE à la longueur actuelle
        cos = self.cos[:, :T]
        sin = self.sin[:, :T]
        
        # 1. Token Embedding
        x = self.wte(idx)  # (B, T) → (B, T, n_embd)
        
        # 2. Normalisation post-embedding
        x = rms_norm(x)
        
        # 3. Passe à travers les blocs
        for block in self.blocks:
            x = block(x, cos, sin)
        
        # 4. Normalisation finale
        x = rms_norm(x)
        
        # 5. Projection vers le vocabulaire
        logits = self.lm_head(x)  # (B, T, vocab_size)
        
        # 6. Logit softcap (stabilisation, style Karpathy)
        softcap = 15.0
        logits = softcap * torch.tanh(logits / softcap)
        
        # 7. Calcul de la loss si targets fournis
        if targets is not None:
            # Cross-entropy loss
            loss = F.cross_entropy(
                logits.view(-1, logits.size(-1)),
                targets.view(-1),
                ignore_index=-1  # Ignore padding
            )
            return loss
        
        return logits
    
    @torch.inference_mode()
    def generate(
        self,
        idx: torch.Tensor,
        max_new_tokens: int,
        temperature: float = 1.0,
        top_k: Optional[int] = None
    ) -> Generator[int, None, None]:
        """
        Génère du texte token par token (streaming)
        
        🎯 Analogie : C'est comme compléter une phrase mot par mot
        - On regarde les mots précédents
        - On "vote" pour le prochain mot
        - temperature = créativité (1.0 = normal, 0 = déterministe)
        - top_k = on ne considère que les K meilleurs mots
        
        Args:
            idx: Tokens de départ (batch, seq)
            max_new_tokens: Combien de tokens générer
            temperature: Contrôle la "créativité" (0 = greedy, 1 = sampling)
            top_k: Ne considère que les K tokens les plus probables
        
        Yields:
            Les tokens générés un par un
        """
        for _ in range(max_new_tokens):
            # Tronque si trop long
            idx_cond = idx if idx.size(1) <= self.config.sequence_len else \
                       idx[:, -self.config.sequence_len:]
            
            # Forward pass
            logits = self.forward(idx_cond)
            logits = logits[:, -1, :]  # Dernier token seulement
            
            # Top-K filtering
            if top_k is not None:
                v, _ = torch.topk(logits, min(top_k, logits.size(-1)))
                logits[logits < v[:, [-1]]] = float('-inf')
            
            # Sampling
            if temperature > 0:
                probs = F.softmax(logits / temperature, dim=-1)
                next_token = torch.multinomial(probs, num_samples=1)
            else:
                next_token = torch.argmax(logits, dim=-1, keepdim=True)
            
            # Ajoute le nouveau token
            idx = torch.cat([idx, next_token], dim=1)
            
            yield next_token.item()


# ==============================================================================
# 🧪 TEST DU MODÈLE
# ==============================================================================

def test_nodus_gpt():
    """Test rapide du modèle"""
    print("\n" + "=" * 60)
    print("🧪 TEST NODUS GPT")
    print("=" * 60)
    
    # Configuration mini pour test
    config = NodusGPTConfig(
        sequence_len=64,
        vocab_size=256,  # Petit vocab pour test
        n_layer=2,
        n_head=2,
        n_embd=64
    )
    
    # Crée le modèle
    model = NodusGPT(config)
    
    # Test forward pass
    batch_size = 2
    seq_len = 16
    x = torch.randint(0, config.vocab_size, (batch_size, seq_len))
    
    print(f"\n📥 Input shape: {x.shape}")
    
    # Sans targets
    logits = model(x)
    print(f"📤 Output (logits) shape: {logits.shape}")
    
    # Avec targets (calcul de loss)
    targets = torch.randint(0, config.vocab_size, (batch_size, seq_len))
    loss = model(x, targets)
    print(f"📉 Loss: {loss.item():.4f}")
    
    # Test génération
    print("\n🎲 Test génération (5 tokens):")
    prompt = torch.randint(0, config.vocab_size, (1, 5))
    generated = list(model.generate(prompt, max_new_tokens=5, temperature=1.0))
    print(f"   Tokens générés: {generated}")
    
    print("\n✅ Tous les tests passent !")
    print("=" * 60)


if __name__ == "__main__":
    test_nodus_gpt()

