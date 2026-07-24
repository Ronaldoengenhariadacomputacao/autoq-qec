"""
AutoQ QEC Estimator
Multi-code fault-tolerant quantum error correction estimator.
"""
from .qec_estimator import (
    CircuitProfile,
    HardwareProfile,
    CodeResult,
    extract_circuit_profile,
    estimate,
    compare,
)
from .real_hardware import CalibratedHardware, HARDWARE_PROFILES
from .recommender import rank, rank_by_metric, Recommendation
from .algorithm_estimator import AlgorithmEstimator, AlgorithmEstimate

__version__ = "3.4.2"
__all__ = [
    "CircuitProfile", "HardwareProfile", "CodeResult",
    "CalibratedHardware", "HARDWARE_PROFILES",
    "Recommendation",
    "AlgorithmEstimator", "AlgorithmEstimate",
    "extract_circuit_profile", "estimate", "compare", "rank", "rank_by_metric",
]
