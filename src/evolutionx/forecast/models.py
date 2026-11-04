"""Forecasting models (numpy only, deterministic). Binary models return P(y = 1); rv models return log RV.

B0 climatology, B1 EWMA-Gaussian, M1 logistic / ridge, M2 boosted depth-2 trees, H1 = M1 + simulator features.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .domain import Target

EPS = 1e-4


def phi(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def clip_p(p: np.ndarray | float) -> np.ndarray | float:
    return np.clip(p, EPS, 1 - EPS)


class Model:
    name = "model"
    uses_features = True

    def fit(self, X: np.ndarray, y: np.ndarray, target: Target) -> None:
        raise NotImplementedError

    def predict(self, x: np.ndarray, target: Target, sigma_h: float) -> float:
        raise NotImplementedError


class Climatology(Model):
    name = "B0_climatology"
    uses_features = False

    def fit(self, X: np.ndarray, y: np.ndarray, target: Target) -> None:
        self.v = float((y.sum() + 1) / (len(y) + 2)) if target.kind == "binary" else float(np.mean(y))

    def predict(self, x: np.ndarray, target: Target, sigma_h: float) -> float:
        return self.v


class EwmaGauss(Model):
    name = "B1_ewma_gauss"
    uses_features = False

    def fit(self, X: np.ndarray, y: np.ndarray, target: Target) -> None:
        pass

    def predict(self, x: np.ndarray, target: Target, sigma_h: float) -> float:
        if target.kind == "rv":
            return math.log(100 * sigma_h + 1e-9)
        if target.direction:
            return 0.5
        assert target.threshold is not None
        return float(clip_p(2 * (1 - phi(target.threshold / max(sigma_h, 1e-9)))))


@dataclass
class _Std:
    mu: np.ndarray = field(default_factory=lambda: np.zeros(0))
    sd: np.ndarray = field(default_factory=lambda: np.ones(0))

    def fit(self, X: np.ndarray) -> np.ndarray:
        self.mu, self.sd = X.mean(0), X.std(0)
        self.sd = np.where(self.sd > 0, self.sd, 1.0)
        return (X - self.mu) / self.sd

    def __call__(self, X: np.ndarray) -> np.ndarray:
        return (X - self.mu) / self.sd


class Logistic(Model):
    """L2 logistic regression by Newton/IRLS (binary) or ridge regression (rv), on standardized features."""

    name = "M1_logistic"

    def __init__(self, l2: float = 1.0) -> None:
        self.l2 = l2
        self.std = _Std()

    def fit(self, X: np.ndarray, y: np.ndarray, target: Target) -> None:
        Z = np.c_[np.ones(len(X)), self.std.fit(X)]
        R = self.l2 * np.eye(Z.shape[1])
        R[0, 0] = 0.0
        if target.kind == "rv":
            self.w = np.linalg.solve(Z.T @ Z + R, Z.T @ y)
            return
        w = np.zeros(Z.shape[1])
        w[0] = math.log((y.mean() + 1e-3) / (1 - y.mean() + 1e-3))
        for _ in range(30):
            with np.errstate(over="ignore"):
                p = 1 / (1 + np.exp(-(Z @ w)))
            g = Z.T @ (p - y) + R @ w
            H = (Z * (p * (1 - p))[:, None]).T @ Z + R
            try:
                step = np.linalg.solve(H, g)
            except np.linalg.LinAlgError:  # saturated probabilities make the unregularised intercept singular
                step = np.linalg.lstsq(H, g, rcond=None)[0]  # only used when solve fails: results otherwise identical
            w -= step
            if np.max(np.abs(step)) < 1e-8:
                break
        self.w = w

    def z(self, x: np.ndarray) -> np.ndarray:
        return self.std(x)

    def predict(self, x: np.ndarray, target: Target, sigma_h: float) -> float:
        s = float(self.w[0] + self.std(x) @ self.w[1:])
        return s if target.kind == "rv" else float(clip_p(1 / (1 + math.exp(-s))))


class GBM(Model):
    """Gradient boosting with depth-2 regression trees (Newton leaves for logistic loss). Deterministic."""

    name = "M2_gbm"

    def __init__(self, rounds: int = 100, lr: float = 0.05, min_leaf: int = 30, n_thresholds: int = 16) -> None:
        self.rounds, self.lr, self.min_leaf, self.nq = rounds, lr, min_leaf, n_thresholds

    def _split(self, X: np.ndarray, g: np.ndarray, idx: np.ndarray) -> tuple[int, float] | None:
        best, out = 0.0, None
        G = g[idx].sum()
        n = len(idx)
        for j in range(X.shape[1]):
            xs = X[idx, j]
            for th in self.thr[j]:
                left = xs <= th
                nl = int(left.sum())
                if nl < self.min_leaf or n - nl < self.min_leaf:
                    continue
                gl = g[idx][left].sum()
                gain = gl * gl / nl + (G - gl) ** 2 / (n - nl) - G * G / n
                if gain > best:
                    best, out = gain, (j, float(th))
        return out

    def _tree(self, X: np.ndarray, g: np.ndarray, h: np.ndarray) -> list[Any]:
        """[(j, th) | None, [(sub_split | None, leaf_values) for left, right]] - depth <= 2, Newton leaves."""

        def leaf(idx: np.ndarray) -> float:
            return float(g[idx].sum() / max(h[idx].sum(), 1e-9))

        root = np.arange(len(X))
        s = self._split(X, g, root)
        if s is None:
            return [None, []]
        j, th = s
        sides = []
        for idx in (root[X[:, j] <= th], root[X[:, j] > th]):
            s2 = self._split(X, g, idx)
            if s2 is None:
                sides.append((None, [leaf(idx)]))
            else:
                j2, th2 = s2
                sides.append(((j2, th2), [leaf(idx[X[idx, j2] <= th2]), leaf(idx[X[idx, j2] > th2])]))
        return [(j, th), sides]

    @staticmethod
    def _apply(tree: list[Any], x: np.ndarray) -> np.ndarray:
        if tree[0] is None:
            return np.zeros(len(x))
        j, th = tree[0]
        out = np.empty(len(x))
        for k, mask in enumerate((x[:, j] <= th, x[:, j] > th)):
            sub, vals = tree[1][k]
            if sub is None:
                out[mask] = vals[0]
            else:
                j2, th2 = sub
                out[mask] = np.where(x[mask, j2] <= th2, vals[0], vals[1])
        return out

    def fit(self, X: np.ndarray, y: np.ndarray, target: Target) -> None:
        self.binary = target.kind == "binary"
        self.thr = [np.unique(np.quantile(X[:, j], np.linspace(0.05, 0.95, self.nq))) for j in range(X.shape[1])]
        if self.binary:
            m = float(np.clip(y.mean(), 1e-3, 1 - 1e-3))
            self.f0 = math.log(m / (1 - m))
        else:
            self.f0 = float(y.mean())
        F = np.full(len(y), self.f0)
        self.trees = []
        for _ in range(self.rounds):
            if self.binary:
                p = 1 / (1 + np.exp(-F))
                g, h = y - p, p * (1 - p)
            else:
                g, h = y - F, np.ones(len(y))
            t = self._tree(X, g, h)
            self.trees.append(t)
            F += self.lr * self._apply(t, X)

    def predict(self, x: np.ndarray, target: Target, sigma_h: float) -> float:
        xx = x[None, :]
        s = self.f0 + self.lr * sum(float(self._apply(t, xx)[0]) for t in self.trees)
        return s if not self.binary else float(clip_p(1 / (1 + math.exp(-s))))


def make(name: str, **kw: Any) -> Model:
    if name.startswith("CAND:"):  # evolution candidate: a frozen-space config, never code
        import json

        spec = json.loads(name[5:])
        if spec["model"] == "logistic":
            m: Model = Logistic(l2=float(spec.get("l2", 1.0)))
        elif spec["model"] == "gbm":
            m = GBM(
                rounds=int(spec.get("rounds", 100)),
                lr=float(spec.get("lr", 0.05)),
                min_leaf=int(spec.get("min_leaf", 30)),
            )
        else:
            raise ValueError(f"unknown candidate model {spec['model']}")
        m.name = name
        return m
    if name == "B0_climatology":
        return Climatology()
    if name == "B1_ewma_gauss":
        return EwmaGauss()
    if name in ("M1_logistic", "H1_hybrid"):
        m = Logistic(**kw)
        m.name = name
        return m
    if name == "M2_gbm":
        return GBM(**kw)
    raise ValueError(name)
