from celery import Celery
import time


celery_app = Celery(
    "tasks",
    broker="amqp://guest:guest@localhost:5672",
    backend="redis://localhost:6379"
)


@celery_app.task
def add(x, y):
    time.sleep(5)
    return x + y

@celery_app.task
def devide(x, y):
    time.sleep(5)
    return x / y

