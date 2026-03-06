from celery import Celery
from app.config import REDIS_URL

celery = Celery("tasks", broker="amqp://guest:guest@rabbitmq:5672//")

@celery.task
def send_alert(transaction_id: int):
    print(f"High risk alert for transaction {transaction_id}")
