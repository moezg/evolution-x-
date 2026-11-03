"""Live simulation session driven by a background thread at a configurable speed."""

from __future__ import annotations

import threading
import time
from typing import Any

from ..sim.config import Shock, SimConfig
from ..sim.scenarios import scenario_at
from ..sim.simulation import Simulation


class LiveSession:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.sim: Simulation | None = None
        self.status = "idle"  # idle | running | paused | finished | stopped
        self.speed = 10.0  # virtual seconds per wall second; <=0 means "max"
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.scenario = "baseline"

    def start(self, seed: int, duration_s: int, scenario: str, speed: float, scale: float = 1.0,
              mode: str = "synthetic", replay_dataset: str | None = None, shock_at_s: int | None = None) -> None:
        self.stop_thread()
        cfg = SimConfig(seed=seed, duration_s=duration_s, scale=scale, mode=mode,  # type: ignore[arg-type]
                        replay_dataset=replay_dataset, invariant_check_every_s=60)
        cfg = scenario_at(scenario, shock_at_s if shock_at_s is not None else min(900, duration_s // 2)).apply(cfg)
        with self.lock:
            self.sim = Simulation(cfg)
            self.scenario = scenario
            self.speed = speed
            self.status = "running"
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="live-sim")
        self._thread.start()

    def _loop(self) -> None:
        tick = 0.1
        while not self._stop.is_set():
            t0 = time.perf_counter()
            with self.lock:
                sim = self.sim
                if sim is None:
                    return
                if self.status == "running":
                    step_ms = 60_000 if self.speed <= 0 else max(1, int(self.speed * tick * 1000))
                    sim.run_until(sim.now + step_ms)
                    if sim.finished:
                        self.status = "stopped" if sim.stopped else "finished"
                        return
            time.sleep(max(0.0, tick - (time.perf_counter() - t0)))

    def pause(self) -> None:
        with self.lock:
            if self.status == "running":
                self.status = "paused"

    def resume(self) -> None:
        with self.lock:
            if self.status == "paused":
                self.status = "running"

    def set_speed(self, speed: float) -> None:
        with self.lock:
            self.speed = speed

    def emergency_stop(self) -> None:
        with self.lock:
            if self.sim:
                self.sim.stop()
            self.status = "stopped"
        self._stop.set()

    def inject(self, shock: Shock) -> None:
        with self.lock:
            if not self.sim:
                raise RuntimeError("no simulation")
            self.sim.inject(shock)

    def stop_thread(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

    def snapshot(self, fn: Any, *args: Any) -> Any:
        with self.lock:
            if self.sim is None:
                return None
            return fn(self.sim, *args)
