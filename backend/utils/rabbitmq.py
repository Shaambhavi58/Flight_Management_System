"""
utils/rabbitmq.py
==================
RabbitMQ Message Producer and Consumer classes.

MessageProducer — publishes serialized flight dicts to 'flights.morning' exchange.
MessageConsumer — consumes messages from the queue, saves flights via FlightService,
                  and runs in a background daemon thread with automatic retry/backoff.
"""

import pika        # RabbitMQ Python client (AMQP 0-9-1)
import json        # serialize/deserialize flight dicts as JSON messages
import threading   # run consumer in a daemon background thread
import time        # sleep between retry attempts
from services.service import FlightService  # business logic layer for flight creation


# ── Queue / Exchange Configuration ────────────────────────────────────────────
RABBITMQ_HOST = "localhost"              # RabbitMQ broker host
EXCHANGE_NAME = "flights.morning"       # direct exchange — routes by ROUTING_KEY
QUEUE_NAME    = "morning_flights_queue" # durable queue bound to the exchange
ROUTING_KEY   = "flight.morning.data"  # binding key used by publisher and consumer


class MessageProducer:
    """
    Publishes flight data messages to the RabbitMQ 'flights.morning' exchange.
    Used by flight_publisher.py to send the daily schedule to the consumer.
    """

    def __init__(self, host: str = RABBITMQ_HOST):
        self._host       = host
        self._connection = None   # pika blocking connection (lazy — opened on first publish)
        self._channel    = None   # AMQP channel for publishing

    def connect(self):
        """
        Open a blocking connection to RabbitMQ and declare the exchange.
        The exchange is declared as durable so it survives broker restarts.
        """
        self._connection = pika.BlockingConnection(
            pika.ConnectionParameters(host=self._host)
        )
        self._channel = self._connection.channel()

        # Declare the direct exchange — idempotent if already exists
        self._channel.exchange_declare(
            exchange=EXCHANGE_NAME,
            exchange_type="direct",  # messages routed by exact routing key match
            durable=True             # exchange survives broker restart
        )

    def publish(self, flight_data: dict):
        """
        Publish a single flight dict as a persistent JSON message to the exchange.
        Reconnects automatically if the channel has been closed.
        """
        # Auto-reconnect if channel was closed since last publish
        if not self._channel or self._channel.is_closed:
            self.connect()

        message = json.dumps(flight_data)  # serialize dict to JSON string

        self._channel.basic_publish(
            exchange=EXCHANGE_NAME,
            routing_key=ROUTING_KEY,   # broker uses this to route to the bound queue
            body=message,              # message payload (bytes)
            properties=pika.BasicProperties(
                delivery_mode=2,               # 2 = persistent — survives broker restart
                content_type="application/json",
            ),
        )
        print(f"[Producer] Published: {flight_data['flight_number']}")

    def publish_batch(self, flights: list):
        """
        Open a connection, publish all flights in the list, then close.
        Batch publishing is more efficient than opening/closing per message.
        """
        self.connect()                  # one connection for the whole batch
        for flight in flights:
            self.publish(flight)        # publish each flight dict
        self.close()                    # release the connection after batch completes

    def close(self):
        """Close the RabbitMQ connection if it is still open."""
        if self._connection and not self._connection.is_closed:
            self._connection.close()


class MessageConsumer:
    """
    Consumes flight messages from the RabbitMQ queue and persists them
    to the MySQL database via FlightService.
    Runs in a background daemon thread with automatic reconnect/retry.
    """

    def __init__(self, host: str = RABBITMQ_HOST):
        self._host       = host
        self._connection = None
        self._channel    = None
        self._service    = FlightService()  # business logic for creating flights in DB
        self._running    = False            # tracks whether the consumer loop is active

    def connect(self):
        """
        Open a connection to RabbitMQ and set up the exchange, queue, and binding.
        basic_qos(prefetch_count=1) ensures fair dispatch — one message at a time per consumer.
        """
        self._connection = pika.BlockingConnection(
            pika.ConnectionParameters(host=self._host)
        )
        self._channel = self._connection.channel()

        # Declare exchange (idempotent — safe to call even if already declared)
        self._channel.exchange_declare(
            exchange=EXCHANGE_NAME, exchange_type="direct", durable=True
        )

        # Declare the durable queue so messages are not lost on restart
        self._channel.queue_declare(queue=QUEUE_NAME, durable=True)

        # Bind the queue to the exchange using the routing key
        self._channel.queue_bind(
            queue=QUEUE_NAME,
            exchange=EXCHANGE_NAME,
            routing_key=ROUTING_KEY
        )

        # Fair dispatch — process one message fully before receiving the next
        self._channel.basic_qos(prefetch_count=1)

    def _on_message(self, channel, method, properties, body):
        """
        Callback invoked by pika for each message delivered from the queue.
        Deserializes the JSON body, saves the flight to the DB, and ACKs.
        On failure, NACKs without requeue to prevent infinite retry loops.
        """
        try:
            flight_data = json.loads(body)  # deserialize JSON bytes → dict
            print(f"[Consumer] Received: {flight_data.get('flight_number', '?')}")
            print("Creating flight:", flight_data.get('flight_number', '?'))

            # Use a synthetic admin context — the airport_id is already in the message
            # so no RBAC override is needed here
            system_user = {"id": 0, "username": "system", "role": "admin", "airport_id": None}

            # Delegate flight creation to the service layer (handles duplicates, validation)
            result = self._service.create_flight(flight_data, current_user=system_user)
            print(f"[Consumer] Saved flight ID: {result['id']}")

            # Send ACK — message is removed from the queue only after successful processing
            channel.basic_ack(delivery_tag=method.delivery_tag)

        except Exception as e:
            print(f"[Consumer] Error processing message: {e}")
            # NACK without requeue — prevents a bad message from looping forever
            channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

    def start_consuming(self):
        """
        Start the blocking consume loop.
        Registers _on_message as the callback for every message delivered to the queue.
        Blocks indefinitely — run this in a separate thread.
        """
        self.connect()
        self._running = True

        # Register our callback and begin listening (blocking call)
        self._channel.basic_consume(queue=QUEUE_NAME, on_message_callback=self._on_message)
        print(f"[Consumer] Waiting for messages on queue '{QUEUE_NAME}'...")

        try:
            self._channel.start_consuming()  # enters the blocking I/O loop
        except Exception as e:
            print(f"[Consumer] Stopped: {e}")
        finally:
            self._running = False  # mark as stopped so retry logic can restart it

    def start_in_thread(self) -> threading.Thread:
        """
        Launch the consumer in a background daemon thread.
        Daemon thread — dies automatically when the main process exits.
        Returns the thread object so callers can monitor it if needed.
        """
        thread = threading.Thread(target=self._start_with_retry, daemon=True)
        thread.start()
        return thread

    def _start_with_retry(self):
        """
        Retry connecting to RabbitMQ with exponential backoff.
        Attempts up to 10 times before giving up.
        Used when the app starts before RabbitMQ is fully ready.
        """
        max_retries = 10

        for attempt in range(1, max_retries + 1):
            try:
                print(f"[Consumer] Connection attempt {attempt}/{max_retries}...")
                self.start_consuming()   # blocking — returns only on disconnect
                break                   # successful — exit retry loop

            except pika.exceptions.AMQPConnectionError:
                # RabbitMQ not yet available — wait with increasing backoff
                wait = min(attempt * 2, 30)  # max 30 seconds between retries
                print(f"[Consumer] RabbitMQ not available. Retrying in {wait}s...")
                time.sleep(wait)

            except Exception as e:
                # Unexpected error — short wait and retry
                print(f"[Consumer] Unexpected error: {e}. Retrying in 5s...")
                time.sleep(5)

    def stop(self):
        """
        Gracefully stop the consumer loop and close the connection.
        """
        if self._channel:
            self._channel.stop_consuming()   # signal the blocking loop to exit

        if self._connection and not self._connection.is_closed:
            self._connection.close()         # release the TCP connection

        self._running = False
