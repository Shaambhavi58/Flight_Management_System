"""
RabbitMQ Message Producer and Consumer classes.

MessageProducer — publishes flight data to the 'flights.morning' exchange.
MessageConsumer — consumes messages from the queue and stores them via FlightService.
"""

import pika
import json
import threading
import time
from services.service import FlightService


RABBITMQ_HOST = "localhost"
EXCHANGE_NAME = "flights.morning"
QUEUE_NAME = "morning_flights_queue"
ROUTING_KEY = "flight.morning.data"


class MessageProducer:
    """
    Publishes flight messages to the RabbitMQ exchange 'flights.morning'.
    """

    def __init__(self, host: str = RABBITMQ_HOST):
        self._host = host
        self._connection = None
        self._channel = None

    def connect(self):
        """Establish connection and declare the exchange."""
        self._connection = pika.BlockingConnection(
            pika.ConnectionParameters(host=self._host)
        )
        self._channel = self._connection.channel()
        self._channel.exchange_declare(
            exchange=EXCHANGE_NAME, exchange_type="direct", durable=True
        )

    def publish(self, flight_data: dict):
        """Publish a single flight message to the exchange."""
        if not self._channel or self._channel.is_closed:
            self.connect()

        message = json.dumps(flight_data)
        self._channel.basic_publish(
            exchange=EXCHANGE_NAME,
            routing_key=ROUTING_KEY,
            body=message,
            properties=pika.BasicProperties(
                delivery_mode=2,  # persistent
                content_type="application/json",
            ),
        )
        print(f"[Producer] Published: {flight_data['flight_number']}")

    def publish_batch(self, flights: list):
        """Publish multiple flight messages."""
        self.connect()
        for flight in flights:
            self.publish(flight)
        self.close()

    def close(self):
        """Close the connection."""
        if self._connection and not self._connection.is_closed:
            self._connection.close()


class MessageConsumer:
    """
    Consumes flight messages from the RabbitMQ queue and saves them
    to the database via FlightService.
    """

    def __init__(self, host: str = RABBITMQ_HOST):
        self._host = host
        self._connection = None
        self._channel = None
        self._service = FlightService()
        self._running = False

    def connect(self):
        """Establish connection, declare exchange and queue, bind them."""
        self._connection = pika.BlockingConnection(
            pika.ConnectionParameters(host=self._host)
        )
        self._channel = self._connection.channel()

        # Declare exchange and queue
        self._channel.exchange_declare(
            exchange=EXCHANGE_NAME, exchange_type="direct", durable=True
        )
        self._channel.queue_declare(queue=QUEUE_NAME, durable=True)
        self._channel.queue_bind(
            queue=QUEUE_NAME, exchange=EXCHANGE_NAME, routing_key=ROUTING_KEY
        )

        # Fair dispatch — one message at a time
        self._channel.basic_qos(prefetch_count=1)

    def _on_message(self, channel, method, properties, body):
        """Callback for each received message."""
        try:
            flight_data = json.loads(body)
            print(f"[Consumer] Received: {flight_data.get('flight_number', '?')}")
            print("Creating flight:", flight_data.get('flight_number', '?'))

            # Use a system-level admin context (airport_id already in message)
            system_user = {"id": 0, "username": "system", "role": "admin", "airport_id": None}

            # Save to database via FlightService
            result = self._service.create_flight(flight_data, current_user=system_user)
            print(f"[Consumer] Saved flight ID: {result['id']}")

            channel.basic_ack(delivery_tag=method.delivery_tag)
        except Exception as e:
            print(f"[Consumer] Error processing message: {e}")
            channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

    def start_consuming(self):
        """Start consuming messages (blocking call)."""
        self.connect()
        self._running = True
        self._channel.basic_consume(queue=QUEUE_NAME, on_message_callback=self._on_message)
        print(f"[Consumer] Waiting for messages on queue '{QUEUE_NAME}'...")
        try:
            self._channel.start_consuming()
        except Exception as e:
            print(f"[Consumer] Stopped: {e}")
        finally:
            self._running = False

    def start_in_thread(self) -> threading.Thread:
        """Start the consumer in a background daemon thread."""
        thread = threading.Thread(target=self._start_with_retry, daemon=True)
        thread.start()
        return thread

    def _start_with_retry(self):
        """Retry connecting to RabbitMQ with backoff."""
        max_retries = 10
        for attempt in range(1, max_retries + 1):
            try:
                print(f"[Consumer] Connection attempt {attempt}/{max_retries}...")
                self.start_consuming()
                break
            except pika.exceptions.AMQPConnectionError:
                wait = min(attempt * 2, 30)
                print(f"[Consumer] RabbitMQ not available. Retrying in {wait}s...")
                time.sleep(wait)
            except Exception as e:
                print(f"[Consumer] Unexpected error: {e}. Retrying in 5s...")
                time.sleep(5)

    def stop(self):
        """Stop consuming."""
        if self._channel:
            self._channel.stop_consuming()
        if self._connection and not self._connection.is_closed:
            self._connection.close()
        self._running = False
