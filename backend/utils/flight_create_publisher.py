"""
utils/flight_create_publisher.py
==================================
Publishes user-initiated single flight creation requests to the
'flight_create_queue' RabbitMQ queue.

Called by: controllers/flight_controller.py → POST /flights
Consumed by: worker.py

End-to-end flow:
  Frontend → POST /flights
          → flight_controller resolves airport_id, adds audit metadata
          → publish_flight_create(data) → RabbitMQ (flight_create_queue)
          → worker.py picks up the message
          → FlightService.create_flight() → MySQL DB
"""

import pika          # AMQP client for RabbitMQ
import json          # serialize flight dict to JSON
import os            # read environment variables
from dotenv import load_dotenv

# Load .env so RABBITMQ_* variables are available when this module is imported
load_dotenv()

# ── Queue configuration ───────────────────────────────────────────────────────
QUEUE_NAME    = "flight_create_queue"                       # dedicated queue for user-created flights
RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")     # broker address from .env
RABBITMQ_PORT = int(os.getenv("RABBITMQ_PORT", "5672"))     # default AMQP port
RABBITMQ_USER = os.getenv("RABBITMQ_USER", "guest")         # broker username
RABBITMQ_PASS = os.getenv("RABBITMQ_PASS", "guest")         # broker password


def _get_connection() -> pika.BlockingConnection:
    """
    Create and return a new authenticated blocking connection to RabbitMQ.
    Called once per publish — the connection is closed immediately after
    the message is sent to prevent idle connection accumulation.
    """
    # Build credentials object from env vars
    credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS)

    # Define all connection parameters
    params = pika.ConnectionParameters(
        host=RABBITMQ_HOST,
        port=RABBITMQ_PORT,
        credentials=credentials,
        heartbeat=600,                      # send heartbeat every 600s to keep connection alive
        blocked_connection_timeout=300,     # raise error if broker blocks us for 300s
    )

    return pika.BlockingConnection(params)   # open the TCP connection and AMQP handshake


def publish_flight_create(data: dict) -> bool:
    """
    Publish a flight creation request dict to the 'flight_create_queue'.

    Args:
        data: Flight data dict. Must include airport_id (already resolved by controller).
              Internal keys (prefixed '_') are stripped by the repository before DB insert.

    Returns:
        True if the message was published successfully.

    Raises:
        RuntimeError: If RabbitMQ is unreachable or any other error occurs.
                      Controller catches this and returns HTTP 503 to the client.
    """
    connection = None   # initialize to None so finally block is safe

    try:
        connection = _get_connection()      # open fresh connection for this publish
        channel    = connection.channel()   # open a logical channel on the connection

        # Declare the queue as durable — safe to call even if it already exists.
        # Durable = queue survives a RabbitMQ broker restart, messages are not lost.
        channel.queue_declare(queue=QUEUE_NAME, durable=True)

        # Serialize the flight dict to a JSON string for transport
        message = json.dumps(data)

        channel.basic_publish(
            exchange="",                # empty string = default exchange (direct to queue)
            routing_key=QUEUE_NAME,    # route directly to this queue by name
            body=message,              # JSON payload as the message body
            properties=pika.BasicProperties(
                delivery_mode=2,               # 2 = persistent — survives broker restart
                content_type="application/json",
            ),
        )

        print(f"[Publisher] Queued flight: {data.get('flight_number', '?')} → {QUEUE_NAME}")
        return True  # signal success to caller

    except pika.exceptions.AMQPConnectionError as e:
        # RabbitMQ is not running or unreachable — surface a clear error message
        raise RuntimeError(
            f"RabbitMQ unavailable at {RABBITMQ_HOST}:{RABBITMQ_PORT}. "
            f"Start RabbitMQ and try again. ({e})"
        )

    except Exception as e:
        # Any other error (serialization, channel error, etc.)
        raise RuntimeError(f"Failed to publish flight: {e}")

    finally:
        # Always close the connection — even if an error occurred
        # This prevents leaked connections accumulating in RabbitMQ
        if connection and not connection.is_closed:
            connection.close()
