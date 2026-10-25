# sends flagged transactions to the queue. sqs on AWS, a plain list when running locally
import json
import os


class MemoryQueue:
    def __init__(self):
        self.events = []

    def publish(self, event):
        self.events.append(event)


class SqsQueue:
    def __init__(self):
        import boto3

        self.client = boto3.client("sqs")
        self.url = os.environ["FLAGGED_QUEUE_URL"]

    def publish(self, event):
        self.client.send_message(QueueUrl=self.url, MessageBody=json.dumps(event))
