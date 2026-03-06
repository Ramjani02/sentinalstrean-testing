from pydantic import BaseModel

class TransactionCreate(BaseModel):
    amount: float
    location: str

class TransactionResponse(BaseModel):
    id: int
    risk_score: float
    decision: str
