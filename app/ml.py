import numpy as np
from sklearn.ensemble import IsolationForest

model = IsolationForest()
model.fit(np.random.rand(100, 2))

def predict_risk(amount: float):
    score = model.decision_function([[amount, amount/10]])
    return float(abs(score[0]))
