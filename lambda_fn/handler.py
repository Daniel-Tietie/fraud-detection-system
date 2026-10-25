# lambda that runs when flagged transactions arrive in the SQS queue
# for each message it saves the flagged transaction to dynamodb, then sends an alert through sns
# sqs can deliver the same message twice. saving to dynamodb twice is fine (same key),
# but a retry could send a duplicate alert email, which is acceptable for an alert
import json
import logging
import os
from decimal import Decimal

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# created on first use and reused after that, so the connection isn't rebuilt for every message
_table = None
_sns = None


def table():
    global _table
    if _table is None:
        _table = boto3.resource("dynamodb").Table(os.environ["FLAGGED_TABLE"])
    return _table


def sns():
    global _sns
    if _sns is None:
        _sns = boto3.client("sns")
    return _sns


def process(event):
    # save the flagged transaction for record keeping
    table().put_item(Item={
        "transaction_id": event["transaction_id"],
        "account_id": event["account_id"],
        "amount": event["amount"],  # already a Decimal (see handler)
        "transaction_type": event["transaction_type"],
        "location": event["location"],
        "timestamp": event["timestamp"],
        "reasons": event["reasons"],
    })

    # then send the alert email
    reasons = "\n- ".join(event["reasons"])
    message = f"""Suspicious activity on account {event['account_id']}.

Transaction: {event['transaction_type']} of {event['amount']} in {event['location']} at {event['timestamp']}
Why it was flagged:
- {reasons}

If this was not you, please contact your bank immediately."""
    sns().publish(
        TopicArn=os.environ["ALERT_TOPIC_ARN"],
        Subject="Possible fraud on your account",
        Message=message,
    )


def handler(sqs_event, context):
    failures = []
    for record in sqs_event["Records"]:
        try:
            # parse_float=Decimal because dynamodb doesn't accept python floats
            process(json.loads(record["body"], parse_float=Decimal))
        except Exception:
            logger.exception("Failed to process message %s", record["messageId"])
            failures.append({"itemIdentifier": record["messageId"]})
    # only the failed messages go back to the queue, the rest get deleted
    return {"batchItemFailures": failures}
