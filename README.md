# Bale Scraper

**An event-driven data pipeline for scraping a messaging platform at scale.**

Bale Scraper collects data from public channels on [Bale](https://bale.ai) (a widely used Iranian messaging platform), and publishes it as a stream of events so that any number of downstream services can consume and build on top of it — without ever touching the scraper's code.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [How It Works](#how-it-works)
- [Project Structure](#project-structure)
- [Data Model](#data-model)
- [API Endpoints](#api-endpoints)
- [Getting Started](#getting-started)
  - [Prerequisites](#prerequisites)
  - [Environment Variables](#environment-variables)
  - [Running Locally](#running-locally)
  - [Running with Docker](#running-with-docker)
- [Deployment](#deployment)
- [Roadmap](#roadmap)
- [License](#license)

---

## Overview

Most scrapers are one-off scripts: fragile, hard to schedule reliably, and tightly coupled to whatever consumes their output. This project was built to avoid all three problems.

- **Reliable at scale** — scraping runs are triggered and orchestrated by Apache Airflow, not a plain cron job, so every run has retries, task dependencies, and full execution history.
- **Realistic scraping** — Playwright drives a real browser session, so the scraper handles dynamic, JavaScript-heavy content instead of relying on a fragile HTTP client.
- **Fully decoupled** — every scraped record is persisted in MongoDB and, at the same time, published as an event to Apache Kafka. Other services consume this stream independently, with no direct dependency on the scraper.
- **Cloud-native** — the whole stack is containerized and deployed on Kubernetes, with self-healing, horizontal scaling, and zero-downtime rolling deployments. No Celery is used anywhere in this design; Kafka handles all asynchronous, decoupled processing.

## Architecture

```
                         ┌─────────────────┐
                         │  Apache Airflow  │
                         │  (scheduling)    │
                         └────────┬─────────┘
                                  │ POST /scrape-channels
                                  ▼
┌──────────────┐        ┌──────────────────┐
│ Bale platform │◄──────►│  Scraper service  │
│  (target)     │ scrapes│ Python · Playwright│
└──────────────┘        │      FastAPI       │
                         └─────────┬─────────┘
                                   │
                     ┌─────────────┴─────────────┐
                     ▼                            ▼
             ┌───────────────┐           ┌────────────────┐
             │    MongoDB     │           │  Apache Kafka   │
             │  (storage)     │           │    (topic)      │
             └───────────────┘           └────────┬────────┘
                                                    │
                                                    ▼
                                       ┌────────────────────────┐
                                       │   Downstream services    │
                                       │ (independent consumers)  │
                                       └────────────────────────┘
```

Everything above the Kafka boundary is owned by this project. Everything below it is owned and run independently by whichever team consumes the topic.

## Tech Stack

| Layer              | Technology                |
|--------------------|----------------------------|
| Scraping           | Python, Playwright         |
| Service layer      | FastAPI                    |
| Orchestration      | Apache Airflow              |
| Messaging          | Apache Kafka (confluent-kafka) |
| Storage            | MongoDB (PyMongo)           |
| Containerization   | Docker                      |
| Deployment         | Kubernetes                  |
| CI/CD              | *(add your pipeline, e.g. GitLab CI / GitHub Actions)* |

## How It Works

1. **Scheduling** — an Airflow DAG calls `POST /scrape-channels` on a fixed interval. The endpoint acquires a distributed lock (backed by MongoDB with a TTL index) so overlapping runs can't happen; if a previous run crashed and never released the lock, it expires automatically after `SCRAPE_LOCK_TIMEOUT` seconds.
2. **Scraping** — `scrape_all_channels()` drives a Playwright browser session against Bale's active channels and parses each message (`scraper/parser.py`) into a structured record: `title`, `body`, `link`, `category`, `source_type`, `published_at`, plus the technical fields `msg_date` and `msg_sid` used only for parsing.
3. **Persistence** — each parsed record is deduplicated using a SHA-256 hash of `title + body` (`content_hash`) and inserted into the `news` collection in MongoDB. Duplicate inserts are silently skipped via a unique index on `content_hash`.
4. **Publishing** — the same record (with the technical `msg_date`/`msg_sid` fields stripped out) is published to a Kafka topic as `{"op": ..., "source": "bale", "o": <record>}`, decoupling the scraper from anything that happens next.
5. **Consumption** — downstream services run their own independent Kafka consumers against this topic, with zero coupling to the scraper's codebase.
6. **Querying** — `GET /get-news` exposes the stored news with pagination, free-text search over `title`/`body`, and optional date filtering on `published_at`.

## Project Structure

```
bale-scraper/
├── api/
│   └── routers.py         # FastAPI routes: /scrape-channels, /get-news
├── scraper/
│   ├── bale_scraper.py    # drives Playwright across all active channels
│   ├── parser.py          # extracts title/body/link/category from a message
│   └── locks.py           # acquire_lock / release_lock (MongoDB-backed)
├── db/
│   ├── mongodb/
│   │   ├── mongo.py       # client, collections, indexes
│   │   └── crud.py        # save_news, get_news_from_db
│   └── kafka/
│       └── producer.py    # send_news_to_kafka, flush_kafka
├── dags/                   # Airflow DAG definitions
├── deploy/
│   └── k8s/                # Kubernetes manifests
├── Dockerfile
├── requirements.txt
└── README.md
```

## Data Model

### MongoDB Collections

| Collection          | Purpose                                                | Index |
|-----------------------|---------------------------------------------------------|-------|
| `news`                 | One document per scraped, deduplicated message           | `content_hash` (unique) |
| `channels`             | Registered channels to scrape                             | `channel_id` (unique) |
| `scrape_locks`         | Distributed lock so only one scrape run executes at a time | `expire_at` (TTL, `expireAfterSeconds=0`) |
| `scrape_errors`        | Errors encountered during scraping                         | `created_at` (TTL, auto-deleted after 30 days) |

> The `news` collection name itself is configurable via `MONGO_COLLECTION_NAME` (defaults to `news`).

**`news` document**

```json
{
  "_id": "ObjectId",
  "title": "string",
  "body": "string",
  "link": "string | null",
  "category": "string",
  "source_type": "string",
  "published_at": "ISODate (Iran timezone, UTC+03:30)",
  "content_hash": "sha256(title|body)"
}
```

- `content_hash` is computed as `sha256(f"{title}|{body}")` and used purely to prevent duplicate inserts; it's excluded from `GET /get-news` responses.
- `category` comes from the `@mention` inside the message when present, otherwise falls back to the channel title.
- `source_type` defaults to `"bale_channel"` unless a different channel type is passed in.

**`channels` document** (fields as registered per channel)

```json
{
  "_id": "ObjectId",
  "channel_id": "string"
}
```

> Extend this with whatever additional fields your channel-registration logic actually stores (title, type, active flag, etc.) — only `channel_id` is confirmed as a unique key in the current code.

**`scrape_locks` document**

```json
{
  "_id": "string",
  "expire_at": "ISODate"
}
```

MongoDB automatically deletes the lock document once `expire_at` is reached, so a crashed run can't block future scrapes forever.

**`scrape_errors` document**

```json
{
  "_id": "ObjectId",
  "created_at": "ISODate"
}
```

> Extend this with whatever error detail fields (channel_id, message, traceback) your error-logging code actually writes.

### Kafka Message Format

There is a single configurable topic (`KAFKA_TOPIC`). Every message published to it follows the same envelope:

```json
{
  "op": "i",
  "source": "bale",
  "o": {
    "title": "string",
    "body": "string",
    "link": "string | null",
    "category": "string",
    "source_type": "string",
    "published_at": "ISO 8601 string"
  }
}
```

- `op` marks the operation type (defaults to `"i"` for insert).
- `source` identifies where the record came from (defaults to `"bale"`).
- `o` is the news record itself — identical to the `news` document above, minus `content_hash`, and with the technical `msg_date`/`msg_sid` fields stripped out before publishing.
- `published_at` is serialized to an ISO 8601 string since raw `datetime` objects aren't JSON-serializable.

Delivery is asynchronous (`producer.produce` + `poll(0)`); `flush_kafka()` must be called before the process exits to guarantee buffered messages are actually sent and delivery callbacks fire.

## API Endpoints

| Method | Path                | Description |
|--------|----------------------|--------------|
| `POST` | `/scrape-channels`     | Triggered by Airflow. Acquires the scrape lock, scrapes all active channels, and returns a summary (`channels_succeeded`, `channels_failed`, `details`). Returns `409` if a run is already in progress. |
| `GET`  | `/get-news`            | Paginated, searchable list of stored news. Supports `q` (free-text search on title/body), `page_number`, `page_size` (max 100), `start_date`, `end_date` (ISO-8601, assumed Iran timezone if no offset is given). |

`GET /get-news` response shape:

```json
{
  "_metadata": {
    "total_count": 0,
    "total_page": 0,
    "page_number": 1,
    "per_page": 10,
    "time_elapsed": 0.0
  },
  "records": []
}
```

## Getting Started

### Prerequisites

- Python 3.11+
- Docker & Docker Compose
- Access to a Kafka broker
- Access to a MongoDB instance
- Apache Airflow (local or remote)

### Environment Variables

Create a `.env` file in the project root:

```env
# MongoDB
MONGO_URI=mongodb://localhost:27017
MONGO_DB_NAME=bale_crawler
MONGO_COLLECTION_NAME=news
MONGO_USERNAME=
MONGO_PASSWORD=

# Kafka
KAFKA_BROKER_URL=localhost:9092
KAFKA_TOPIC=bale.news

# Scraping
SCRAPE_LOCK_TIMEOUT=600
```

### Running Locally

```bash
git clone https://github.com/<your-username>/bale-scraper.git
cd bale-scraper
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install --with-deps
uvicorn api.main:app --reload
```

### Running with Docker

```bash
docker build -t bale-scraper .
docker run --env-file .env -p 8000:8000 bale-scraper
```

## Deployment

The service is deployed on Kubernetes. Manifests live under `deploy/k8s/` and include:

- Deployment for the scraper/API service
- ConfigMaps and Secrets for configuration
- Services and Ingress for external access

```bash
kubectl apply -f deploy/k8s/
```

## Roadmap

- [ ] Add automated tests for the scraper and parser
- [ ] Add Prometheus metrics and Grafana dashboards
- [ ] Add rate limiting / backoff tuning for scraping
- [ ] Add CI/CD pipeline

## License

This project is licensed under the [MIT License](LICENSE).
