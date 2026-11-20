"""
AutoQ QEC Estimator
Multi-code fault-tolerant quantum error correction estimator.
"""
from .algorithm_estimator import AlgorithmEstimate, AlgorithmEstimator
from .qec_estimator import (
    CircuitProfile,
    CodeResult,
    HardwareProfile,
    compare,
    estimate,
    extract_circuit_profile,
)
from .real_hardware import HARDWARE_PROFILES, CalibratedHardware
from .recommender import Recommendation, rank, rank_by_metric

__version__ = "3.4.7"
__all__ = [
    "CircuitProfile", "HardwareProfile", "CodeResult",
    "CalibratedHardware", "HARDWARE_PROFILES",
    "Recommendation",
    "AlgorithmEstimator", "AlgorithmEstimate",
    "extract_circuit_profile", "estimate", "compare", "rank", "rank_by_metric",
]
