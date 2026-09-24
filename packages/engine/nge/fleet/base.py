"""GPU fleet interface + value types."""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class GpuNode:
    id: str
    gpu_type: str = "H100"
    region: str = "eu-north1"
    state: str = "ready"            # provisioning | ready | allocated | releasing | gone
    job: Optional[str] = None

    def as_dict(self) -> Dict:
        return {"id": self.id, "gpu_type": self.gpu_type, "region": self.region,
                "state": self.state, "job": self.job}


@dataclass
class GpuNodeStatus:
    id: str
    state: str
    util_pct: float
    mem_used_gb: float
    mem_total_gb: float
    temp_c: float
    power_w: float
    health: str                    # ok | warm | throttle | unknown
    efficiency: float = 0.0
    # How metrics were obtained — not the *label* on the node (nb-h100-*).
    probe_kind: str = "unknown"    # nvidia-smi | cpu-fallback | synthetic | failed
    gpu_class: str = "none"        # datacenter | consumer | synthetic | none
    gpu_name: str = ""             # nvidia-smi product name when known

    def as_dict(self) -> Dict:
        return self.__dict__.copy()


class GpuFleet(abc.ABC):
    mode: str = "abstract"

    @abc.abstractmethod
    def provision(self, n: int, gpu_type: str = "H100") -> List[GpuNode]:
        ...

    @abc.abstractmethod
    def status(self, node_id: Optional[str] = None) -> List[GpuNodeStatus]:
        ...

    @abc.abstractmethod
    def allocate(self, job: str, node_id: Optional[str] = None) -> GpuNode:
        ...

    @abc.abstractmethod
    def release(self, node_ids: Optional[List[str]] = None) -> List[str]:
        ...
