from fastapi import FastAPI, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import SessionLocal, engine, Base
from app.schemas import TransactionCreate, TransactionResponse
from app.models import Transaction
from app.services import process_transaction
from app.idempotency import check_key, store_key

app = FastAPI()

@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def get_db():
    async with SessionLocal() as session:
        yield session

@app.post("/transaction", response_model=TransactionResponse)
async def create_transaction(
    tx: TransactionCreate,
    db: AsyncSession = Depends(get_db),
    idempotency_key: str = Header(None)
):
    if idempotency_key:
        existing = check_key(idempotency_key)
        if existing:
            return TransactionResponse.parse_raw(existing)

    risk_score, decision = await process_transaction(tx.amount, tx.location)

    transaction = Transaction(
        user_id=1,
        amount=tx.amount,
        location=tx.location,
        risk_score=risk_score,
        decision=decision
    )

    db.add(transaction)
    await db.commit()
    await db.refresh(transaction)

    response = TransactionResponse(
        id=transaction.id,
        risk_score=risk_score,
        decision=decision
    )

    if idempotency_key:
        store_key(idempotency_key, response.json())

    return response
