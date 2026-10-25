# the REST API will receive the transaction details and login attempts, then run the fraud rules on them
import logging
import uuid
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Literal

from fastapi import Depends, FastAPI
from pydantic import BaseModel, Field

from . import fraud
from .config import get_settings  # the config.py file I created for the settings
from .queue import MemoryQueue, SqsQueue
from .store import DynamoStore, MemoryStore, ts_key

logger = logging.getLogger("fraud-api")
app = FastAPI(title="Banking Fraud Detection API")


@lru_cache
def get_store():
    return DynamoStore() if get_settings().storage_backend == "dynamodb" else MemoryStore()


@lru_cache
def get_queue():
    return SqsQueue() if get_settings().queue_backend == "sqs" else MemoryQueue()


def as_utc(ts):
    # if the timestamp has no timezone, treat it as UTC, otherwise convert it to UTC
    return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts.astimezone(timezone.utc)


# what a transaction request has to look like, fastapi checks it before code runs
class TransactionIn(BaseModel):
    account_id: str = Field(min_length=1)  # can't be empty
    amount: float = Field(gt=0)  # has to be more than 0
    transaction_type: Literal["withdrawal", "deposit", "transfer"]  # only these 3 are allowed
    location: str = Field(min_length=1)
    timestamp: datetime


# same idea but for a login attempt, success is true or false
class LoginAttemptIn(BaseModel):
    account_id: str = Field(min_length=1)
    success: bool
    timestamp: datetime


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/login-attempts", status_code=201)
def record_login_attempt(body: LoginAttemptIn, store=Depends(get_store)):
    # saves the login attempt so rule 3 can count the failed ones
    store.save_login_attempt({
        "attempt_id": str(uuid.uuid4()),
        "account_id": body.account_id,
        "success": body.success,
        "timestamp": as_utc(body.timestamp),
    })
    return {"recorded": True}


@app.post("/transactions", status_code=201)
def create_transaction(body: TransactionIn, store=Depends(get_store), queue=Depends(get_queue)):
    # runs the transaction through the fraud rules, returns approved or flagged with the reasons
    settings = get_settings()
    ts = as_utc(body.timestamp)
    transaction_id = str(uuid.uuid4())

    # get the history the rules need (last transaction and recent failed logins)
    previous = store.last_transaction_before(body.account_id, ts)
    window_start = ts - timedelta(minutes=settings.failed_login_window_min)
    failed_logins = store.count_failed_logins(body.account_id, window_start, ts)

    reasons = fraud.evaluate(
        body.transaction_type, body.amount, body.location, ts, previous, failed_logins, settings
    )
    # no reasons means approved, anything else is flagged
    status = "flagged" if reasons else "approved"

    # save every transaction, not just flagged ones, rule 2 needs the previous one to compare
    store.save_transaction({
        "transaction_id": transaction_id,
        "account_id": body.account_id,
        "amount": body.amount,
        "transaction_type": body.transaction_type,
        "location": body.location,
        "timestamp": ts,
        "status": status,
    })

    # only flagged transactions get sent to the queue
    alert_queued = None
    if status == "flagged":
        try:
            queue.publish({
                "transaction_id": transaction_id,
                "account_id": body.account_id,
                "amount": body.amount,
                "transaction_type": body.transaction_type,
                "location": body.location,
                "timestamp": ts_key(ts),
                "reasons": reasons,
            })
            alert_queued = True
        except Exception:
            # decision is already saved, so don't lose it just because the queue failed
            logger.exception("Failed to publish flagged transaction %s", transaction_id)
            alert_queued = False

    return {
        "transaction_id": transaction_id,
        "status": status,
        "reasons": reasons,
        "alert_queued": alert_queued,
    }
