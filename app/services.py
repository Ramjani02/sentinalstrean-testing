from app.rule_engine import evaluate_rules
from app.ml import predict_risk
from app.tasks import send_alert

async def process_transaction(amount: float, location: str):
    rule_flag = evaluate_rules(amount, location)
    risk_score = predict_risk(amount)

    decision = "APPROVED"

    if rule_flag or risk_score > 0.5:
        decision = "DECLINED"

    return risk_score, decision
