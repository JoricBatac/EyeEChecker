"""Temperature scaling on the validation split."""

from __future__ import annotations

import numpy as np
import torch
from torch import nn


def fit_temperature(logits: np.ndarray, labels: np.ndarray, max_iter: int = 200) -> float:
    lt = torch.tensor(logits, dtype=torch.float32)
    yt = torch.tensor(labels, dtype=torch.long)
    log_t = torch.zeros(1, requires_grad=True)
    opt = torch.optim.LBFGS([log_t], lr=0.05, max_iter=max_iter)
    loss_fn = nn.CrossEntropyLoss()

    def closure() -> torch.Tensor:
        opt.zero_grad()
        loss = loss_fn(lt / log_t.exp(), yt)
        loss.backward()
        return loss

    opt.step(closure)
    return float(log_t.exp().clamp(0.05, 20).item())
