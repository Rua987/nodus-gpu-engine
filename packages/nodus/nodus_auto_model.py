#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Architecture NODUS pour inference locale (plan bridge, probes).

Miroir de test_generate.NodusAutoModel (repo train) — meme poids .pt.
Le harnais reste autonome : pas d'import depuis le repo de recherche.
"""

from __future__ import annotations

from dataclasses import dataclass

import torch
import torch.nn as nn
import torch.nn.functional as F

from nodus_gpt import NodusGPTConfig, precompute_rotary_embeddings, rms_norm
from nodus_spinoza_gpt import SpinozistAttention
from nodus_spinoza_moe_gpt import SpinozistMoELayer
from nodus_spinozist_reasoning import SpinozistReasoningLayer


@dataclass
class NodusAutoConfig:
    sequence_len: int = 512
    vocab_size: int = 100277
    n_layer: int = 24
    n_head: int = 12
    n_embd: int = 768
    n_experts: int = 1
    dropout: float = 0.0
    rope_scaling: float = 1.0
    use_conatus_gate: bool = True
    use_illusion_filter: bool = True
    use_geometric_necessity: bool = True
    use_reasoning_layer: bool = False

    def to_nodus_config(self) -> NodusGPTConfig:
        return NodusGPTConfig(
            sequence_len=self.sequence_len,
            vocab_size=self.vocab_size,
            n_layer=self.n_layer,
            n_head=self.n_head,
            n_embd=self.n_embd,
            dropout=self.dropout,
            rope_scaling=self.rope_scaling,
        )


class NodusAutoBlock(nn.Module):
    def __init__(self, config: NodusAutoConfig, with_reasoning: bool = False):
        super().__init__()
        nodus_config = config.to_nodus_config()
        self.attn = SpinozistAttention(nodus_config)
        self.moe = SpinozistMoELayer(nodus_config, n_experts=config.n_experts)
        if config.use_reasoning_layer and with_reasoning:
            self.reasoning = SpinozistReasoningLayer(nodus_config)
        else:
            self.reasoning = None

    def forward(self, x, cos, sin):
        x = x + self.attn(rms_norm(x), cos, sin)
        x = x + self.moe(rms_norm(x))
        if self.reasoning is not None:
            reasoning_output, _ = self.reasoning(rms_norm(x), should_reason=True)
            x = x + reasoning_output
        return x


class NodusAutoModel(nn.Module):
    def __init__(self, config: NodusAutoConfig):
        super().__init__()
        self.config = config
        self.wte = nn.Embedding(config.vocab_size, config.n_embd)
        self.blocks = nn.ModuleList([
            NodusAutoBlock(config, with_reasoning=(i == config.n_layer - 1))
            for i in range(config.n_layer)
        ])
        self.lm_head = nn.Linear(config.n_embd, config.vocab_size, bias=False)
        head_dim = config.n_embd // config.n_head
        self.register_buffer(
            "cos",
            torch.zeros(1, config.sequence_len, 1, head_dim // 2),
        )
        self.register_buffer(
            "sin",
            torch.zeros(1, config.sequence_len, 1, head_dim // 2),
        )
        cos, sin = precompute_rotary_embeddings(
            config.sequence_len,
            head_dim,
            device=None,
            scaling_factor=config.rope_scaling,
        )
        self.cos = cos
        self.sin = sin

    def forward(self, idx, targets=None):
        B, T = idx.size()
        device = idx.device
        cos = self.cos[:, :T].to(device)
        sin = self.sin[:, :T].to(device)
        x = self.wte(idx)
        x = rms_norm(x)
        for block in self.blocks:
            x = block(x, cos, sin)
        x = rms_norm(x)
        logits = self.lm_head(x)
        softcap = 15.0
        logits = softcap * torch.tanh(logits / softcap)
        if targets is not None:
            loss = F.cross_entropy(
                logits.view(-1, logits.size(-1)),
                targets.view(-1),
            )
            return logits, loss
        return logits
