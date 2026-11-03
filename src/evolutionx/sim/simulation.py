"""Simulation orchestrator: wires world, exchange, clearing, agents and network.

Single-threaded, deterministic discrete-event loop. Given the same SimConfig
(including seed) and code version, every run produces an identical event
history; `Simulation.fingerprint()` hashes that history for replay tests.
"""

from __future__ import annotations

import hashlib
import math
import random
import time
from typing import Any

from ..agents.base import Agent, CancelAll, Limit, Market, Observation, validate_command
from ..agents.population import build_population, population_counts
from ..agents.social import SocialNetwork, reputation_from_return
from ..kernel.clearing import ClearingHouse
from ..kernel.events import EventQueue, SimEvent
from ..kernel.exchange import Exchange, VenueConfig
from ..kernel.marketdata import MarketDataFeed, take_snapshot
from ..kernel.orderbook import BUY, SELL
from ..kernel.units import btc_to_lots, usd_to_cash, usd_to_ticks
from ..strategies import POLICIES
from ..strategies.params import clip_params
from .config import Shock, SimConfig
from .world import News, World

TICK_MS = 1000
MAX_CMD_LOTS = 2_000_000


class Simulation:
    def __init__(self, cfg: SimConfig) -> None:
        self.historical: dict[str, Any] | None = None
        if cfg.mode == "replay":
            from .replay import load_replay_path

            self.historical = load_replay_path(cfg.replay_dataset, cfg.duration_s)
            cfg = cfg.model_copy(update={"initial_price_usd": self.historical["first_close"]})
        self.cfg = cfg
        self.counts = population_counts(cfg.scale, cfg.population_overrides)
        self.agents: list[Agent] = build_population(
            cfg.seed, self.counts, cfg.n_venues, cfg.param_overrides, cfg.heterogeneity
        )
        self.clearing = ClearingHouse(cfg.n_venues, cfg.maker_fee_bps, cfg.taker_fee_bps, cfg.maintenance_margin)
        for a in self.agents:
            self.clearing.open_account(a.id, usd_to_cash(a.capital_usd), a.max_leverage)
        self.p0 = usd_to_ticks(cfg.initial_price_usd)
        self.exchange = Exchange(
            [VenueConfig(f"venue_{chr(65 + i)}", cfg.circuit_breaker_pct) for i in range(cfg.n_venues)],
            self.clearing,
            self.p0,
        )
        self.world = World(
            cfg.seed, cfg.initial_price_usd, cfg.world_annual_vol, cfg.news_rate_per_hour, cfg.news_impact
        )
        if self.historical is not None:
            self.world.replay = self.historical["path"]
        self.feed = MarketDataFeed()
        self.social = SocialNetwork(len(self.agents), cfg.seed, cfg.social_k, cfg.social_rewire_p, cfg.social_enabled)
        self.q = EventQueue()
        self.rng = random.Random(f"sim:{cfg.seed}")
        self.funding_rate = 0.0
        self.funding_override: tuple[float, int] | None = None
        self.sim_events: list[SimEvent] = []
        self.influence_events: list[dict[str, Any]] = []
        self.liquidation_log: list[dict[str, Any]] = []
        self.series: list[tuple] = []  # per-second public market state
        self.candles: list[dict[int, list[float]]] = [{} for _ in range(cfg.n_venues)]
        self._trade_cursor = 0
        self.external: dict[str, int] = {}
        self.invalid_commands = 0
        self.wall_time_s = 0.0
        self.events_processed = 0
        self.stopped = False
        self._schedule_initial()

    # ------------------------------------------------------------------ setup
    def _schedule_initial(self) -> None:
        q = self.q
        q.schedule(0, "tick", None, priority=0)
        for a in self.agents:
            first = a.rng.randint(0, 500) if a.kind == "market_maker" else a.rng.randint(1000, max(1001, a.wake_ms))
            q.schedule(first, "wake", a.id)
        q.schedule(self.cfg.funding_interval_s * 1000, "funding", None, priority=1)
        q.schedule(60_000, "perf", None, priority=2)
        for i, s in enumerate(self.cfg.shocks):
            if s.type == "whale_liquidation":
                self._setup_whale(i, s)
            if s.armed:
                q.schedule(s.at_s * 1000, "shock", i, priority=1)

    def _setup_whale(self, i: int, s: Shock) -> None:
        lots = btc_to_lots(s.magnitude)
        notional_usd = s.magnitude * self.cfg.initial_price_usd
        aid = len(self.agents) + len(self.external)
        self.clearing.open_account(aid, usd_to_cash(notional_usd / 5), 10, external=True)
        self.external[f"whale_{i}"] = aid
        start, end = 60_000, max(120_000, s.at_s * 1000 - 120_000)
        n = max(1, (end - start) // 5000)
        chunk = max(1, lots // n)
        for k in range(n):
            self.q.schedule(
                start + k * 5000,
                "ext_order",
                (aid, 0 if k % 2 == 0 else min(1, self.cfg.n_venues - 1), BUY, chunk, False),
                priority=3,
            )

    # ------------------------------------------------------------------ run
    @property
    def now(self) -> int:
        return self.q.now

    def run(self) -> Simulation:
        self.run_until(self.cfg.duration_s * 1000)
        return self

    def run_until(self, t_end_ms: int) -> None:
        t_end_ms = min(t_end_ms, self.cfg.duration_s * 1000)
        start = time.perf_counter()
        q = self.q
        handlers = {
            "tick": self._tick,
            "wake": self._wake,
            "orders": self._orders,
            "funding": self._funding,
            "perf": self._perf,
            "shock": self._shock,
            "ext_order": self._ext_order,
            "restore": self._restore,
        }
        while q and not self.stopped:
            nt = q.peek_time()
            if nt is None or nt > t_end_ms:
                break
            t, kind, payload = q.pop()
            handlers[kind](t, payload)
            self.events_processed += 1
        self.wall_time_s += time.perf_counter() - start

    @property
    def finished(self) -> bool:
        return self.stopped or (self.q.peek_time() or 10**18) > self.cfg.duration_s * 1000

    # ------------------------------------------------------------------ handlers
    def _tick(self, t: int, _: Any) -> None:
        news = self.world.step(t)
        if news is not None:
            self.sim_events.append(
                SimEvent(t, "news", data={"sentiment": round(news.sentiment, 3), "headline": news.headline})
            )
        ex = self.exchange
        ex.update_circuit_breakers(t)
        for aid in ex.run_liquidations(t):
            ev = ex.events[-1]
            kind = self.agents[aid].kind if aid < len(self.agents) else "external"
            self.liquidation_log.append({"t": t, "agent": aid, "kind": kind, **ev.data})
        index = usd_to_ticks(self.world.value_as_of(max(0, t - 60_000)))
        snap = take_snapshot(ex, t, self.funding_rate, index)
        self.feed.publish(snap)
        v0 = snap.venues[0]
        spread = (v0.ask - v0.bid) / v0.mid * 1e4 if v0.ask and v0.bid else float("nan")
        depth = v0.depth_bid + v0.depth_ask
        imb = (v0.depth_bid - v0.depth_ask) / depth if depth else 0.0
        self.series.append(
            (
                t,
                *[vv.mid for vv in snap.venues],
                spread,
                depth,
                imb,
                self.world.value,
                self.funding_rate,
                sum(vv.volume for vv in snap.venues),
                len(self.liquidation_log),
            )
        )
        self._update_candles()
        if self.cfg.invariant_check_every_s and t % (self.cfg.invariant_check_every_s * 1000) == 0:
            ex.check_invariants()
        self.q.schedule(t + TICK_MS, "tick", None, priority=0)

    def _update_candles(self) -> None:
        trades = self.exchange.trades
        for tr in trades[self._trade_cursor :]:
            m = tr.t // 60_000
            c = self.candles[tr.venue].get(m)
            p = tr.price / 100
            if c is None:
                self.candles[tr.venue][m] = [p, p, p, p, tr.qty / 1e4, 1]
            else:
                c[1] = max(c[1], p)
                c[2] = min(c[2], p)
                c[3] = p
                c[4] += tr.qty / 1e4
                c[5] += 1
        self._trade_cursor = len(trades)

    def observe(self, a: Agent, t: int, peek: bool = False) -> Observation | None:
        """Build the agent's legitimate view of the world at time t.

        peek=True is a side-effect-free inspection (dashboard): it neither consumes
        news nor draws from the agent's RNG, so inspecting never perturbs a run.
        """
        data_t = t - a.md_latency_ms
        snap = self.feed.as_of(data_t)
        if snap is None:
            return None
        acct = self.clearing.accounts[a.id]
        marks = [vv.mid for vv in snap.venues]
        news: list[News] = []
        for n in reversed(self.world.news):
            if n.t <= a.last_news_t:
                break
            if n.t <= data_t:
                news.append(n)
        if news:
            news.reverse()
            if not peek:
                a.last_news_t = news[-1].t
        fundamental = None
        if peek and a.memory.get("research"):
            fundamental = float("nan")  # exists, but value is private to the agent's own decision step
        elif a.memory.get("research"):
            # persistent private belief error: AR(1) with ~5 min half-life (heterogeneous beliefs)
            noise_bps = a.params.get("info_noise_bps", 20.0)
            e = a.memory.get("belief_err", a.rng.gauss(0, 1))
            dt_s = max(0.0, (t - a.memory.get("belief_t", t)) / 1000)
            rho = math.exp(-dt_s / 430.0)
            e = rho * e + math.sqrt(max(0.0, 1 - rho * rho)) * a.rng.gauss(0, 1)
            a.memory["belief_err"], a.memory["belief_t"] = e, t
            fundamental = self.world.value_as_of(data_t) * math.exp(noise_bps / 1e4 * e)
        return Observation(
            t=t,
            data_t=snap.t,
            venues=snap.venues,
            funding_rate=snap.funding_rate,
            index_price=snap.index_price,
            cash=acct.cash,
            positions=tuple(acct.positions),
            equity=acct.equity(marks),
            open_orders=len(self.exchange.agent_orders.get(a.id, ())),
            news=tuple(news),
            social=self.social.signal(a.id, self.agents),
            fundamental=fundamental,
        )

    def _wake(self, t: int, aid: int) -> None:
        a = self.agents[aid]
        self.q.schedule(t + max(100, int(a.wake_ms * (0.5 + a.rng.random()))), "wake", aid)
        if not a.active:
            return
        obs = self.observe(a, t)
        if obs is None:
            return
        if not a.mids or a.mids[-1][0] != obs.data_t:
            a.mids.append((obs.data_t, obs.venues[a.home_venue].mid))
        prev = a.stance
        cmds = POLICIES[a.policy_name](a, obs)
        a.wakes += 1
        s = obs.social
        if self.cfg.social_enabled and abs(s) > 0.4 and a.stance * s > 0 and prev * s < 0 and abs(a.stance) > 0.2:
            self.influence_events.append(
                {
                    "t": t,
                    "agent": aid,
                    "kind": a.kind,
                    "social": round(s, 3),
                    "prev": round(prev, 3),
                    "new": round(a.stance, 3),
                }
            )
        valid = []
        for c in cmds:
            if validate_command(c, self.cfg.n_venues, MAX_CMD_LOTS):
                valid.append(c)
            else:
                self.invalid_commands += 1
        if valid:
            self.q.schedule(t + a.order_latency_ms, "orders", (aid, valid), priority=3)

    def _orders(self, t: int, payload: tuple[int, list]) -> None:
        aid, cmds = payload
        ex = self.exchange
        a = self.agents[aid]
        for c in cmds:
            if isinstance(c, CancelAll):
                ex.cancel_all(aid, c.venue)
            elif isinstance(c, Limit):
                ex.submit(t, aid, c.venue, c.side, c.qty, c.price, ioc=c.ioc)
                a.orders_sent += 1
            elif isinstance(c, Market):
                ex.submit(t, aid, c.venue, c.side, c.qty, None)
                a.orders_sent += 1

    def _funding(self, t: int, _: Any) -> None:
        index = usd_to_ticks(self.world.value_as_of(max(0, t - 60_000)))
        marks = self.exchange.marks()
        if self.funding_override and t <= self.funding_override[1]:
            rate = self.funding_override[0]
        else:
            self.funding_override = None
            prem = (sum(marks) / len(marks) - index) / index
            rate = max(-self.cfg.funding_cap, min(self.cfg.funding_cap, self.cfg.funding_k * prem))
        self.funding_rate = rate
        for v, m in enumerate(marks):
            residual = self.clearing.apply_funding(v, rate, m)
            self.sim_events.append(SimEvent(t, "funding", venue=v, data={"rate": rate, "residual": residual}))
        self.q.schedule(t + self.cfg.funding_interval_s * 1000, "funding", None, priority=1)

    def _perf(self, t: int, _: Any) -> None:
        marks = self.exchange.marks()
        rets: dict[int, float] = {}
        for a in self.agents:
            eq = self.clearing.accounts[a.id].equity(marks) / 1e6
            a.equity_curve.append((t, round(eq, 2)))
            a.peak_equity = max(a.peak_equity, eq)
            if a.peak_equity > 0:
                a.max_drawdown = max(a.max_drawdown, 1 - eq / a.peak_equity)
            rets[a.id] = eq / a.capital_usd - 1
            a.reputation = reputation_from_return(rets[a.id])
        if self.cfg.imitation_enabled and t % (self.cfg.imitation_interval_s * 1000) == 0:
            self._imitation(t, rets)
        self.q.schedule(t + 60_000, "perf", None, priority=2)

    def _imitation(self, t: int, rets: dict[int, float]) -> None:
        """Social learning: copy (and slightly mutate) a more successful same-kind peer."""
        by_kind: dict[str, list[Agent]] = {}
        for a in self.agents:
            by_kind.setdefault(a.kind, []).append(a)
        for a in self.agents:
            if self.rng.random() >= self.cfg.imitation_prob:
                continue
            peers = by_kind[a.kind]
            if len(peers) < 2:
                continue
            sample = [peers[self.rng.randrange(len(peers))] for _ in range(3)]
            best = max(sample, key=lambda p: rets[p.id])
            if best.id != a.id and rets[best.id] > rets[a.id] + 0.002:
                new = {k: v * (1 + 0.05 * self.rng.gauss(0, 1)) for k, v in best.params.items()}
                a.record_strategy_change(t, "imitation", clip_params(a.kind, new), best.id)
                self.sim_events.append(SimEvent(t, "imitation", a.id, data={"source": best.id, "kind": a.kind}))

    def _shock(self, t: int, i: int) -> None:
        s = self.cfg.shocks[i]
        self.sim_events.append(SimEvent(t, "shock", data={"type": s.type, "magnitude": s.magnitude, "note": s.note}))
        if s.type == "fundamental_drop":
            self.world.shock(t, -s.magnitude, f"SCENARIO: fundamental repricing {-s.magnitude:+.1%}", -3.0)
        elif s.type == "news_panic":
            self.world.news.append(News(t, -abs(s.magnitude), "SCENARIO: major negative headline", "scenario"))
        elif s.type == "flash_sell":
            aid = len(self.agents) + len(self.external)
            notional = s.magnitude * self.exchange.marks()[0] / 100
            self.clearing.open_account(aid, usd_to_cash(notional), 5, external=True)
            self.external[f"flash_{i}"] = aid
            n = max(1, s.duration_s // 2)
            chunk = max(1, btc_to_lots(s.magnitude) // n)
            for k in range(n):
                self.q.schedule(t + k * 2000, "ext_order", (aid, k % self.cfg.n_venues, SELL, chunk, False), priority=3)
        elif s.type == "liquidity_drought":
            for a in self.agents:
                if a.kind == "market_maker":
                    a.memory["liquidity_scale"] = max(0.0, 1 - s.magnitude)
            self.q.schedule(t + s.duration_s * 1000, "restore", ("liquidity", i), priority=1)
        elif s.type == "whale_liquidation":
            aid = self.external[f"whale_{i}"]
            acct = self.clearing.accounts[aid]
            marks = self.exchange.marks()
            target_eq = int(0.01 * acct.gross_notional(marks))
            withdraw = max(0, acct.equity(marks) - target_eq)
            acct.cash -= withdraw
            self.clearing.external_inflows -= withdraw  # recorded external outflow (collateral seized elsewhere)
        elif s.type == "funding_spike":
            self.funding_override = (s.magnitude, t + s.duration_s * 1000)
            self.funding_rate = s.magnitude
        elif s.type == "arb_outage":
            for a in self.agents:
                if a.kind == "arbitrage":
                    a.memory["disabled_until"] = t + s.duration_s * 1000
                    self.exchange.cancel_all(a.id)

    def _restore(self, t: int, payload: tuple[str, int]) -> None:
        if payload[0] == "liquidity":
            for a in self.agents:
                if a.kind == "market_maker":
                    a.memory["liquidity_scale"] = 1.0
            self.sim_events.append(SimEvent(t, "restore", data={"what": "liquidity"}))

    def _ext_order(self, t: int, payload: tuple[int, int, int, int, bool]) -> None:
        aid, venue, side, qty, forced = payload
        self.exchange.submit(t, aid, venue, side, qty, None, forced=forced)

    # ------------------------------------------------------------------ controls
    def stop(self) -> None:
        """Emergency stop: halts the event loop immediately."""
        self.stopped = True

    def inject(self, shock: Shock) -> None:
        """Inject a shock at the current time (live dashboard)."""
        self.cfg.shocks.append(shock.model_copy(update={"at_s": self.now // 1000}))
        i = len(self.cfg.shocks) - 1
        if shock.type == "whale_liquidation":
            raise ValueError("whale_liquidation needs setup; configure it before the run")
        self.q.schedule(self.now + 1, "shock", i, priority=1)

    # ------------------------------------------------------------------ results
    def fingerprint(self) -> str:
        h = hashlib.sha256()
        for tr in self.exchange.trades:
            h.update(f"{tr.t},{tr.venue},{tr.price},{tr.qty},{tr.buyer},{tr.seller};".encode())
        for aid in sorted(self.clearing.accounts):
            a = self.clearing.accounts[aid]
            h.update(f"{aid}:{a.cash}:{a.positions};".encode())
        return h.hexdigest()

    def series_columns(self) -> list[str]:
        return [
            "t",
            *[f"mid_{i}" for i in range(self.cfg.n_venues)],
            "spread_bps",
            "depth",
            "imbalance",
            "fundamental",
            "funding",
            "volume",
            "liquidations",
        ]
