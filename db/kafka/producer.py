import os
import json
from datetime import datetime

from confluent_kafka import Producer, KafkaException


KAFKA_BROKER_URL = os.getenv("KAFKA_BROKER_URL")
KAFKA_TOPIC = os.getenv("KAFKA_TOPIC")

print(
    f"[KAFKA][CONFIG] "
    f"KAFKA_BROKER_URL={KAFKA_BROKER_URL!r} "
    f"KAFKA_TOPIC={KAFKA_TOPIC!r}"
)

_producer: Producer | None = None

# Counters, just so the final flush log tells you something
# meaningful (how many messages were actually attempted).
_produced_count = 0
_delivered_ok_count = 0
_delivered_failed_count = 0


def _get_producer() -> Producer:
    """
    Lazily creates (and caches) a single Producer instance
    for the whole process.
    """

    global _producer

    if _producer is None:

        if not KAFKA_BROKER_URL:

            raise RuntimeError(
                "KAFKA_BROKER_URL is not set. "
                "Check that .env has this variable AND that "
                "your app actually loads .env (e.g. "
                "load_dotenv() is called before this module "
                "is imported)."
            )

        print(
            f"[KAFKA][INIT] "
            f"creating producer -> "
            f"{KAFKA_BROKER_URL}"
        )

        _producer = Producer(
            {
                "bootstrap.servers": KAFKA_BROKER_URL,
                # Fail fast on connection issues instead of
                # retrying silently for a long time, so
                # broken config shows up quickly in the logs.
                "socket.timeout.ms": 10000,
            }
        )

    return _producer


def _json_default(value):
    """
    Allows datetime objects (e.g. published_at) to be
    serialized to JSON.
    """

    if isinstance(value, datetime):
        return value.isoformat()

    raise TypeError(
        f"Object of type {type(value)} is not JSON serializable"
    )


def _delivery_report(err, msg) -> None:
    """
    Called by confluent-kafka once a message has been
    delivered (or has failed). This only fires when poll()
    or flush() is called AND the broker has responded.
    """

    global _delivered_ok_count, _delivered_failed_count

    if err is not None:

        _delivered_failed_count += 1

        print(
            f"[KAFKA][DELIVERY_FAILED] "
            f"error={err} "
            f"topic={msg.topic() if msg else '?'}"
        )

    else:

        _delivered_ok_count += 1

        print(
            f"[KAFKA][DELIVERY_OK] "
            f"topic={msg.topic()} "
            f"partition={msg.partition()} "
            f"offset={msg.offset()} "
            f"key_size={len(msg.value() or b'')}B"
        )


def send_news_to_kafka(
    data: dict,
    op: str = "i",
    source: str = "bale",
) -> None:
    """
    Publishes a single news item to Kafka using the format:

        {
            "op": op,
            "source": source,
            "o": data
        }
    """

    global _produced_count

    if not KAFKA_TOPIC:

        raise RuntimeError(
            "KAFKA_TOPIC is not set in .env"
        )

    # Internal/technical fields are not part of the public payload.
    clean_data = {
        k: v
        for k, v in data.items()
        if k not in ("msg_date", "msg_sid")
    }

    payload = {
        "op": op,
        "source": source,
        "o": clean_data,
    }

    producer = _get_producer()

    try:

        producer.produce(
            KAFKA_TOPIC,
            value=json.dumps(
                payload,
                default=_json_default,
                ensure_ascii=False,
            ).encode("utf-8"),
            callback=_delivery_report,
        )

        _produced_count += 1

        print(
            f"[KAFKA][PRODUCE] "
            f"queued message #{_produced_count} "
            f"topic={KAFKA_TOPIC} "
            f"title={str(clean_data.get('title'))[:40]!r}"
        )

    except BufferError:

        # Local queue is full -> force a flush and retry once.
        print(
            "[KAFKA][BUFFER_FULL] "
            "local queue full, flushing and retrying..."
        )

        producer.flush(5)

        producer.produce(
            KAFKA_TOPIC,
            value=json.dumps(
                payload,
                default=_json_default,
                ensure_ascii=False,
            ).encode("utf-8"),
            callback=_delivery_report,
        )

        _produced_count += 1

    except KafkaException as e:

        print(
            f"[KAFKA][PRODUCE_ERROR] "
            f"{e}"
        )

        raise

    # Non-blocking: only services callbacks that are already queued.
    producer.poll(0)


def flush_kafka(timeout: float = 10.0) -> None:
    """
    Should be called before the process/context closes,
    to make sure buffered messages are actually sent.

    This is also the moment where most delivery callbacks
    actually fire, since produce() itself is fire-and-forget.
    """

    if _producer is None:

        print(
            "[KAFKA][FLUSH] "
            "no producer was ever created "
            "(send_news_to_kafka was never called "
            "or always failed before reaching producer.produce)."
        )

        return

    print(
        f"[KAFKA][FLUSH] "
        f"flushing... produced={_produced_count} "
        f"delivered_ok_so_far={_delivered_ok_count} "
        f"delivered_failed_so_far={_delivered_failed_count}"
    )

    remaining = _producer.flush(timeout)

    print(
        f"[KAFKA][FLUSH][DONE] "
        f"remaining_undelivered={remaining} "
        f"delivered_ok={_delivered_ok_count} "
        f"delivered_failed={_delivered_failed_count}"
    )

    if remaining > 0:

        print(
            f"[KAFKA][FLUSH][WARNING] "
            f"{remaining} message(s) were still not delivered "
            f"after {timeout}s timeout. Check that the broker "
            f"at {KAFKA_BROKER_URL} is reachable from where "
            f"this process runs."
        )