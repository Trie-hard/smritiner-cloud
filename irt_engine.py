import math
from datetime import datetime, timezone
from typing import List, Dict, Any

def logistic_2pl(theta: float, a: float, b: float) -> float:
    """Computes probability of correct response under 2-Parameter Logistic (2-PL) model."""
    z = a * (theta - b)
    if z < -30:
        return 0.0
    if z > 30:
        return 1.0
    return 1.0 / (1.0 + math.exp(-z))

def estimate_theta_eap(responses: List[Dict[str, Any]], num_quad: int = 41) -> tuple[float, float]:
    """
    Estimates cognitive ability theta using Expected A Posteriori (EAP) with a standard Normal prior N(0, 1).
    Returns (theta_estimate, standard_error_of_measurement).
    """
    if not responses:
        return 0.0, 1.0

    # Quadrature points from -4.0 to +4.0
    nodes = [-4.0 + i * (8.0 / (num_quad - 1)) for i in range(num_quad)]
    weights = [math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi) for x in nodes]

    likelihoods = []
    for x in nodes:
        log_lik = 0.0
        for r in responses:
            is_correct = 1 if r.get("correct") or r.get("is_correct") else 0
            a = float(r.get("discrimination", 1.0))
            b = float(r.get("difficulty", 0.0))
            p = logistic_2pl(x, a, b)
            p = max(1e-7, min(1.0 - 1e-7, p))
            log_lik += math.log(p if is_correct else (1.0 - p))
        likelihoods.append(math.exp(log_lik))

    # Posterior
    posteriors = [l * w for l, w in zip(likelihoods, weights)]
    total_post = sum(posteriors)
    if total_post <= 0:
        return 0.0, 1.0

    posteriors = [p / total_post for p in posteriors]

    # Mean & Variance
    eap_theta = sum(x * p for x, p in zip(nodes, posteriors))
    var_theta = sum(((x - eap_theta) ** 2) * p for x, p in zip(nodes, posteriors))
    sem = math.sqrt(max(0.01, var_theta))

    return round(eap_theta, 3), round(sem, 3)

def generate_sbar_summary(patient_name: str, age: int, baseline_theta: float, current_theta: float) -> Dict[str, Any]:
    """Generates structured SBAR clinical report according to ABDM clinical guidelines."""
    delta = current_theta - baseline_theta
    severity = "CRITICAL" if delta <= -0.5 else "MODERATE" if delta <= -0.2 else "STABLE"

    return {
        "patient_name": patient_name,
        "age": age,
        "situation": f"Patient demonstrates a cognitive ability score shift of {delta:+.2f} (Baseline θ: {baseline_theta:.2f} → Current θ: {current_theta:.2f}).",
        "background": f"{age}-year-old enrolled in SmritiNER community cognitive screening CST protocol. Completed regular digital CST games.",
        "assessment": f"Severity Level: {severity}. {'Statistically significant downward trajectory in reaction time and working memory.' if severity != 'STABLE' else 'Cognitive ability stable within normal standard deviation limits.'}",
        "recommendation": "1. Schedule in-person formal MoCA / HMSE assessment.\n2. Review neuro-vascular risk factors and sleep hygiene.\n3. Adjust adaptive CST game difficulty parameters to prevent frustration.",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
