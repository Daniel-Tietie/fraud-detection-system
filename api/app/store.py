# history storage. rules 2 and 3 need past data, so every transaction and login attempt gets saved here (approved or flagged)
# two versions with the same methods: MemoryStore (local and tests) and DynamoStore (AWS)
# both dynamodb tables use account_id as the partition key and sk as the sort key
# sk = timestamp + "#" + a unique id. the timestamp is a fixed length string so sorting by sk sorts by time,
# and the id stops two items with the same timestamp overwriting each other
import os
from datetime import datetime, timezone
from decimal import Decimal


def ts_key(ts):
    # turns the time into a fixed length UTC string, so alphabetical order is the same as time order
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def parse_ts(value):
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)


class MemoryStore:
    def __init__(self):
        self.transactions = []
        self.logins = []

    def save_transaction(self, txn):
        self.transactions.append(dict(txn))

    def last_transaction_before(self, account_id, ts):
        older = [
            t for t in self.transactions
            if t["account_id"] == account_id and t["timestamp"] < ts
        ]
        return max(older, key=lambda t: t["timestamp"]) if older else None

    def save_login_attempt(self, attempt):
        self.logins.append(dict(attempt))

    def count_failed_logins(self, account_id, start, end):
        # start is included, so an attempt exactly on the cutoff counts (leaning strict)
        return sum(
            1 for a in self.logins
            if a["account_id"] == account_id and not a["success"] and start <= a["timestamp"] <= end
        )


class DynamoStore:
    def __init__(self):
        import boto3

        db = boto3.resource("dynamodb")
        self.transactions = db.Table(os.environ["TRANSACTIONS_TABLE"])
        self.logins = db.Table(os.environ["LOGIN_ATTEMPTS_TABLE"])

    def save_transaction(self, txn):
        self.transactions.put_item(Item={
            "account_id": txn["account_id"],
            "sk": f"{ts_key(txn['timestamp'])}#{txn['transaction_id']}",
            "transaction_id": txn["transaction_id"],
            "amount": Decimal(str(txn["amount"])),  # dynamodb doesn't accept floats
            "transaction_type": txn["transaction_type"],
            "location": txn["location"],
            "timestamp": ts_key(txn["timestamp"]),
            "status": txn["status"],
        })

    def last_transaction_before(self, account_id, ts):
        resp = self.transactions.query(
            KeyConditionExpression="account_id = :a AND sk < :t",
            ExpressionAttributeValues={":a": account_id, ":t": ts_key(ts)},
            ScanIndexForward=False,  # newest first
            Limit=1,
        )
        if not resp["Items"]:
            return None
        item = resp["Items"][0]
        return {"location": item["location"], "timestamp": parse_ts(item["timestamp"])}

    def save_login_attempt(self, attempt):
        self.logins.put_item(Item={
            "account_id": attempt["account_id"],
            "sk": f"{ts_key(attempt['timestamp'])}#{attempt['attempt_id']}",
            "success": attempt["success"],
            "timestamp": ts_key(attempt["timestamp"]),
        })

    def count_failed_logins(self, account_id, start, end):
        kwargs = {
            # "~" sorts after "#", so attempts exactly at the end time are included
            "KeyConditionExpression": "account_id = :a AND sk BETWEEN :s AND :e",
            "FilterExpression": "success = :f",
            "ExpressionAttributeValues": {
                ":a": account_id, ":s": ts_key(start), ":e": ts_key(end) + "~", ":f": False,
            },
            "Select": "COUNT",
        }
        total = 0
        # dynamodb returns results in pages, so keep going until there are no more
        while True:
            resp = self.logins.query(**kwargs)
            total += resp["Count"]
            if "LastEvaluatedKey" not in resp:
                return total
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
