"""Dixon-Coles bivariate-Poisson model for football scorelines."""
from __future__ import annotations

import numpy as np
from scipy.optimize import minimize
from scipy.stats import poisson

MAX_GOALS = 8  # scoreline grid 0..8 per side


def _tau(x: int, y: int, lam: float, mu: float, rho: float) -> float:
    """Dixon-Coles low-score correlation correction."""
    if x == 0 and y == 0:
        return 1 - lam * mu * rho
    if x == 0 and y == 1:
        return 1 + lam * rho
    if x == 1 and y == 0:
        return 1 + mu * rho
    if x == 1 and y == 1:
        return 1 - rho
    return 1.0


def fit_ratings(matches: list[dict], xi: float = 0.0) -> dict:
    """Fit attack/defence per team + home advantage + rho by max likelihood.

    matches: list of {home_id, away_id, hg, ag, weight}
    Returns dict with 'attack', 'defence' (per team), 'home_adv', 'rho'.
    """
    teams = sorted({m["home_id"] for m in matches} | {m["away_id"] for m in matches})
    idx = {t: i for i, t in enumerate(teams)}
    n = len(teams)

    # params: [attack(n), defence(n), home_adv, rho]
    init = np.concatenate([np.zeros(n), np.zeros(n), [0.25], [-0.1]])
    # Bounds keep ratings sane on small samples and rho in its valid small range.
    bounds = ([(-2.0, 2.0)] * n) + ([(-2.0, 2.0)] * n) + [(0.1, 0.5), (-0.2, 0.2)]

    def negloglik(params: np.ndarray) -> float:
        atk = params[:n]
        dfc = params[n:2 * n]
        home_adv = params[2 * n]
        rho = params[2 * n + 1]
        ll = 0.0
        for m in matches:
            i, j = idx[m["home_id"]], idx[m["away_id"]]
            lam = np.exp(atk[i] - dfc[j] + home_adv)
            mu = np.exp(atk[j] - dfc[i])
            hg, ag = m["hg"], m["ag"]
            w = m.get("weight", 1.0)
            p = (poisson.pmf(hg, lam) * poisson.pmf(ag, mu)
                 * _tau(hg, ag, lam, mu, rho))
            ll += w * np.log(max(p, 1e-12))
        # sum-to-zero constraint penalty on attack ratings for identifiability
        ll -= 100 * (atk.sum() ** 2)
        return -ll

    res = minimize(negloglik, init, method="L-BFGS-B", bounds=bounds)
    p = res.x
    return {
        "attack": {t: float(p[idx[t]]) for t in teams},
        "defence": {t: float(p[n + idx[t]]) for t in teams},
        "home_adv": float(p[2 * n]),
        "rho": float(p[2 * n + 1]),
    }


def score_matrix(atk_h: float, dfc_h: float, atk_a: float, dfc_a: float,
                 home_adv: float, rho: float) -> np.ndarray:
    """Return (MAX_GOALS+1 x MAX_GOALS+1) matrix P(home=i, away=j)."""
    lam = np.exp(atk_h - dfc_a + home_adv)
    mu = np.exp(atk_a - dfc_h)
    gh = poisson.pmf(np.arange(MAX_GOALS + 1), lam)
    ga = poisson.pmf(np.arange(MAX_GOALS + 1), mu)
    mat = np.outer(gh, ga)
    for i in (0, 1):
        for j in (0, 1):
            mat[i, j] *= _tau(i, j, lam, mu, rho)
    mat /= mat.sum()
    return mat


def derive_markets(mat: np.ndarray) -> dict:
    """From a score matrix, compute 1X2, exp goals, over2.5, btts, top scoreline."""
    n = mat.shape[0]
    p_home = float(np.tril(mat, -1).sum())   # home goals > away goals
    p_away = float(np.triu(mat, 1).sum())
    p_draw = float(np.trace(mat))
    idx = np.arange(n)
    exp_h = float((mat.sum(axis=1) * idx).sum())
    exp_a = float((mat.sum(axis=0) * idx).sum())
    over25 = float(sum(mat[i, j] for i in range(n) for j in range(n) if i + j >= 3))
    btts = float(sum(mat[i, j] for i in range(1, n) for j in range(1, n)))
    top = np.unravel_index(int(mat.argmax()), mat.shape)
    return {
        "p_home": p_home, "p_draw": p_draw, "p_away": p_away,
        "exp_home_goals": round(exp_h, 2), "exp_away_goals": round(exp_a, 2),
        "over25": round(over25, 3), "btts": round(btts, 3),
        "top_scoreline": f"{top[0]}-{top[1]}",
    }
