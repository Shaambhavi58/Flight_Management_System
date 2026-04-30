"""
FlightCreatePublisher — Publishes user-initiated flight creation requests
to the 'flight_create_queue' RabbitMQ queue.

Flow:
  Frontend → POST /flights → publish_flight_create() → RabbitMQ
                                                              ↓
                                                       worker.py
                                                              ↓
                                                    FlightService.create_flight()
                                                              ↓
                                                            MySQL DB
"""

import pika
import json
import os
from dotenv import load_dotenv

load_dotenv()

QUEUE_NAME   = "flight_create_queue"
RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
RABBITMQ_PORT = int(os.getenv("RABBITMQ_PORT", "5672"))
RABBITMQ_USER = os.getenv("RABBITMQ_USER", "guest")
RABBITMQ_PASS = os.getenv("RABBITMQ_PASS", "guest")


def _get_connection() -> pika.BlockingConnection:
    """Create and return a new RabbitMQ blocking connection."""
    credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS)
    params = pika.ConnectionParameters(
        host=RABBITMQ_HOST,
        port=RABBITMQ_PORT,
        credentials=credentials,
        heartbeat=600,
        blocked_connection_timeout=300,
    )
    return pika.BlockingConnection(params)


def publish_flight_create(data: dict) -> bool:
    """
    Publish a flight creation request to the 'flight_create_queue'.

    Args:
        data: Flight data dict (must include airport_id already resolved by controller).

    Returns:
        True if published successfully, False otherwise.

    Raises:
        RuntimeError: If RabbitMQ connection fails.
    """
    connection = None
    try:
        connection = _get_connection()
        channel = connection.channel()

        # Declare durable queue (idempotent — safe to call every time)
        channel.queue_declare(queue=QUEUE_NAME, durable=True)

        message = json.dumps(data)
        channel.basic_publish(
            exchange="",               # default exchange (direct to queue by name)
            routing_key=QUEUE_NAME,
            body=message,
            properties=pika.BasicProperties(
                delivery_mode=2,       # 2 = persistent — survives broker restart
                content_type="application/json",
            ),
        )
        print(f"[Publisher] Queued flight: {data.get('flight_number', '?')} → {QUEUE_NAME}")
        return True

    except pika.exceptions.AMQPConnectionError as e:
        raise RuntimeError(
            f"RabbitMQ unavailable at {RABBITMQ_HOST}:{RABBITMQ_PORT}. "
            f"Start RabbitMQ and try again. ({e})"
        )
    except Exception as e:
        raise RuntimeError(f"Failed to publish flight: {e}")
    finally:
        if connection and not connection.is_closed:
            connection.close()
