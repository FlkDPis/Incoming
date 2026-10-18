from __future__ import annotations

from ..config import Config
from .base import Backend, BackendError


def create_backend(cfg: Config) -> Backend:
    if cfg.backend == "myfox_cloud":
        from .myfox_cloud import MyfoxCloudBackend

        return MyfoxCloudBackend(cfg)
    if cfg.backend == "demo":
        from .demo import DemoBackend

        return DemoBackend()
    raise BackendError(f"Backend inconnu : {cfg.backend}")
