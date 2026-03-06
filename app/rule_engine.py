def evaluate_rules(amount: float, location: str):
    if amount > 5000:
        return True
    if location.lower() == "unknown":
        return True
    return False
