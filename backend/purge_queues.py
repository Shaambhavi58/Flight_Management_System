import pika
import os
from dotenv import load_dotenv

load_dotenv()

RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
RABBITMQ_PORT = int(os.getenv("RABBITMQ_PORT", "5672"))
RABBITMQ_USER = os.getenv("RABBITMQ_USER", "guest")
RABBITMQ_PASS = os.getenv("RABBITMQ_PASS", "guest")

credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS)
params = pika.ConnectionParameters(
    host=RABBITMQ_HOST,
    port=RABBITMQ_PORT,
    credentials=credentials
)
connection = pika.BlockingConnection(params)
channel = connection.channel()

# Purge both queues
try:
    channel.queue_purge(queue='morning_flights_queue')
    print("Purged morning_flights_queue")
except Exception as e:
    print(f"Error purging morning_flights_queue: {e}")

try:
    channel.queue_purge(queue='flight_create_queue')
    print("Purged flight_create_queue")
except Exception as e:
    print(f"Error purging flight_create_queue: {e}")

connection.close()
