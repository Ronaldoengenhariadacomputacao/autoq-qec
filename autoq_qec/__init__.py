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
from .recommender import rank, Recommendation
from .algorithm_estimator import AlgorithmEstimator, AlgorithmEstimate

__version__ = "3.1.0"
__all__ = [
    "CircuitProfile", "HardwareProfile", "CodeResult",
    "CalibratedHardware", "HARDWARE_PROFILES",
    "Recommendation",
    "AlgorithmEstimator", "AlgorithmEstimate",
    "extract_circuit_profile", "estimate", "compare", "rank",
]
