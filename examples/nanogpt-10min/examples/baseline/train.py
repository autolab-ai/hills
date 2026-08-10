"""A minimal byte-level GPT, written to the submission contract.

It is not tuned. It exists to show what a valid submission looks like: it trains
until the evaluator kills it, and it keeps checkpoints/final.pt up to date the
whole time, written atomically so a kill mid-save cannot corrupt it.

    python train.py --data <hill>/data/train.bin --out <workdir>/checkpoints/
"""

import argparse
import os
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

VOCAB = 256
BLOCK = 512


class CausalSelfAttention(nn.Module):
    def __init__(self, n_embd: int, n_head: int):
        super().__init__()
        self.n_head = n_head
        self.n_embd = n_embd
        self.qkv = nn.Linear(n_embd, 3 * n_embd, bias=False)
        self.proj = nn.Linear(n_embd, n_embd, bias=False)

    def forward(self, x):
        batch = x.size(0)
        length = x.size(1)
        width = self.n_embd
        head_dim = width // self.n_head

        qkv = self.qkv(x)
        q = qkv[:, :, :width].view(batch, length, self.n_head, head_dim).transpose(1, 2)
        k = qkv[:, :, width : 2 * width].view(batch, length, self.n_head, head_dim).transpose(1, 2)
        v = qkv[:, :, 2 * width :].view(batch, length, self.n_head, head_dim).transpose(1, 2)

        attended = F.scaled_dot_product_attention(q, k, v, is_causal=True)
        merged = attended.transpose(1, 2).contiguous().view(batch, length, width)
        return self.proj(merged)


class Block(nn.Module):
    def __init__(self, n_embd: int, n_head: int):
        super().__init__()
        self.ln1 = nn.LayerNorm(n_embd)
        self.attn = CausalSelfAttention(n_embd, n_head)
        self.ln2 = nn.LayerNorm(n_embd)
        self.fc = nn.Linear(n_embd, 4 * n_embd)
        self.out = nn.Linear(4 * n_embd, n_embd)

    def forward(self, x):
        x = x + self.attn(self.ln1(x))
        x = x + self.out(F.gelu(self.fc(self.ln2(x))))
        return x


class GPT(nn.Module):
    def __init__(self, n_layer: int, n_head: int, n_embd: int):
        super().__init__()
        self.wte = nn.Embedding(VOCAB, n_embd)
        self.wpe = nn.Embedding(BLOCK, n_embd)
        self.blocks = nn.ModuleList([Block(n_embd, n_head) for _ in range(n_layer)])
        self.ln_f = nn.LayerNorm(n_embd)
        self.head = nn.Linear(n_embd, VOCAB, bias=False)

    def forward(self, idx):
        length = idx.size(1)
        pos = torch.arange(length, device=idx.device)
        x = self.wte(idx) + self.wpe(pos)
        for block in self.blocks:
            x = block(x)
        return self.head(self.ln_f(x))


def pick_device() -> torch.device:
    if torch.cuda.is_available():
        return torch.device("cuda")
    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def save_atomic(scripted, out_dir: Path) -> None:
    """The evaluator kills this process without warning; never leave a partial file."""
    temporary = out_dir / "final.pt.tmp"
    torch.jit.save(scripted, temporary)
    os.replace(temporary, out_dir / "final.pt")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--lr", type=float, default=3e-4)
    parser.add_argument("--n-layer", type=int, default=4)
    parser.add_argument("--n-head", type=int, default=4)
    parser.add_argument("--n-embd", type=int, default=128)
    parser.add_argument("--save-every-s", type=float, default=5.0)
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    torch.manual_seed(0)
    device = pick_device()

    tokens = torch.from_numpy(np.fromfile(args.data, dtype=np.uint16).astype(np.int64))
    print(f"device {device}  tokens {len(tokens):,}", flush=True)

    model = GPT(args.n_layer, args.n_head, args.n_embd).to(device)
    scripted = torch.jit.script(model)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=0.1)
    print(f"parameters {sum(p.numel() for p in model.parameters()):,}", flush=True)

    save_atomic(scripted, args.out)
    last_save = time.perf_counter()
    step = 0
    while True:
        starts = torch.randint(0, len(tokens) - BLOCK - 1, (args.batch_size,))
        batch_x = torch.stack([tokens[s : s + BLOCK] for s in starts]).to(device)
        batch_y = torch.stack([tokens[s + 1 : s + BLOCK + 1] for s in starts]).to(device)

        logits = model(batch_x)
        loss = F.cross_entropy(logits.view(-1, VOCAB), batch_y.reshape(-1))
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        optimizer.step()

        step += 1
        now = time.perf_counter()
        if now - last_save >= args.save_every_s:
            save_atomic(scripted, args.out)
            last_save = now
            print(f"step {step:6d}  loss {loss.item():.4f}  bpb {loss.item() / 0.6931:.4f}", flush=True)


if __name__ == "__main__":
    main()
