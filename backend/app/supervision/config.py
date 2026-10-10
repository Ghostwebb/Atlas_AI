"""Supervisor policy: versions, thresholds and identifiers.

Every rule threshold lives here. Changing a value changes the policy, so bump
POLICY_VERSION when you do.
"""

SCHEMA_VERSION = "1.0"
POLICY_VERSION = "phase3-v1"

# Minimum magnitude for a score to count as a directional signal.
# Scores in [-1, 1]; |score| < this is treated as neutral (no false conflicts
# around zero). Covered by boundary tests.
DIRECTION_MIN_MAGNITUDE = 0.20

# Confidence below this adds an informational observation (only when no
# contradiction or caution finding already explains the low confidence).
CONFIDENCE_LOW_THRESHOLD = 0.50

# Number of fundamental metrics the analyzer can compute.
EXPECTED_FUNDAMENTAL_METRICS = 4

# Data source identifier -> provenance enum value. Unmapped sources are an error.
PROVENANCE_BY_DATA_SOURCE: dict[str, str] = {
    "demo_dataset": "synthetic",
}

# Score-bearing components the supervisor reasons about, in fixed display order.
COMPONENT_ORDER = ("momentum", "trend", "risk", "fundamental")

# Components needed for a minimal technical evidence base.
CORE_TECHNICAL_COMPONENTS = ("momentum", "trend", "risk")

SEVERITY_RANK = {"critical": 0, "warning": 1, "info": 2}
