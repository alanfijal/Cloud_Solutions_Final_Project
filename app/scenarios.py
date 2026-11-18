"""Deterministic teaching scenarios; a thermal approximation, not a trained model."""

SCENARIOS = {
    "normal": "Normal operation",
    "spike": "Brief temperature spike",
    "door_open": "Door left open",
    "compressor": "Compressor failure",
    "warming": "Gradual warming",
    "disconnect": "Sensor disconnected",
}


def temperature(scenario, sample, total, config):
    if scenario not in SCENARIOS or not 0 <= sample < total:
        raise ValueError("Invalid scenario sample")
    sign = 1 if config["direction"] == "max" else -1
    normal = config["threshold"] - sign * 2
    progress = sample / max(1, total - 1)
    if scenario == "disconnect" and 0.20 <= progress < 0.80:
        return None
    if scenario == "spike":
        return round(normal + sign * (5 if sample == max(1, total // 3) else 0), 1)
    if scenario in ("normal", "disconnect"):
        return round(normal + (0.1 if sample % 2 else -0.1), 1)
    recovery = 0.65 if scenario == "door_open" else 0.78
    value = normal
    # Recompute from the sample number: a retried task generates identical bytes.
    for index in range(sample + 1):
        phase = index / max(1, total - 1)
        target = normal
        if 0.15 <= phase < recovery:
            target += sign * (7 * phase / recovery if scenario == "warming" else 7)
        value += 0.55 * (target - value)
    return round(value, 1)
