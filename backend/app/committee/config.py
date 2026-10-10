"""Committee policy: version, roles, thresholds and precedence. Every value is an explicit rule.

The committee compares perspectives; it does not average scores (they measure different things),
does not pick a winning agent, has no user objective, horizon, risk tolerance or portfolio, and never
produces or confirms an order.
"""

SCHEMA_VERSION = "committee.v1"
POLICY_VERSION = "1.0.0"
AGENTS_SCHEMA_VERSION = "agents.v1.1"   # the committee is defined over this agents contract

OPPORTUNITY = ("argo", "nova", "vector")  # perspectives on potential (ARGO = limited P/E lens)
RISK = "aegis"                            # risk gate, never an extra vote on returns

MIN_PARTICIPANTS = 2            # opportunity perspectives that must be evaluable for any directional reading
MIN_ALIGNED = 2                 # perspectives that must share a direction for an aligned_* conclusion
MIN_INDEPENDENT_BASES = 2       # evidence groups that share no core metric
MIN_COVERAGE_FOR_ALIGNMENT = 0.75  # coverage of each perspective counted towards an alignment

AEGIS_CORE_RISK_CRITERIA = ("volatility", "max_drawdown")
ARGO_VALUATION_CRITERION = "pe_valuation"

# Precedence: the first state whose rule holds is the conclusion.
PRECEDENCE = ("insufficient_data", "conflicted", "aligned_unfavorable", "aligned_favorable", "caution", "neutral")

PAIR_KINDS = {
    frozenset({"nova", "vector"}): "growth_vs_momentum",
    frozenset({"argo", "nova"}): "valuation_vs_growth",
    frozenset({"argo", "vector"}): "valuation_vs_momentum",
}
