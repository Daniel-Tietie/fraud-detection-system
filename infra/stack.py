import os

from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
    aws_cloudwatch as cloudwatch,
    aws_cloudwatch_actions as cw_actions,
    aws_dynamodb as dynamodb,
    aws_ec2 as ec2,
    aws_ecr_assets as ecr_assets,
    aws_ecs as ecs,
    aws_ecs_patterns as ecs_patterns,
    aws_lambda as _lambda,
    aws_lambda_event_sources as event_sources,
    aws_sns as sns,
    aws_sns_subscriptions as subs,
    aws_sqs as sqs,
)
from constructs import Construct

ROOT = os.path.join(os.path.dirname(__file__), "..")


class FraudStack(Stack):
    def __init__(self, scope: Construct, id: str, alert_email: str = None, **kwargs):
        super().__init__(scope, id, **kwargs)

        # ---------- Data ----------
        # history tables for rules 2 and 3, they hold every transaction and login attempt
        def history_table(name):
            return dynamodb.Table(
                self, name,
                partition_key=dynamodb.Attribute(name="account_id", type=dynamodb.AttributeType.STRING),
                sort_key=dynamodb.Attribute(name="sk", type=dynamodb.AttributeType.STRING),
                billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
                removal_policy=RemovalPolicy.DESTROY,  # so cdk destroy deletes the tables, fine for a demo
            )

        transactions_table = history_table("TransactionsTable")
        login_attempts_table = history_table("LoginAttemptsTable")

        # fraud log, only the flagged transactions go here (the table the assignment asks for)
        flagged_table = dynamodb.Table(
            self, "FlaggedTransactionsTable",
            partition_key=dynamodb.Attribute(name="transaction_id", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
        )

        # ---------- Messaging ----------
        dlq = sqs.Queue(self, "FlaggedDlq", retention_period=Duration.days(14))
        queue = sqs.Queue(
            self, "FlaggedQueue",
            # has to be at least the lambda timeout, aws recommends about 6x
            visibility_timeout=Duration.seconds(180),
            dead_letter_queue=sqs.DeadLetterQueue(max_receive_count=3, queue=dlq),
        )

        topic = sns.Topic(self, "FraudAlertTopic", display_name="Fraud alerts")
        if alert_email:
            topic.add_subscription(subs.EmailSubscription(alert_email))

        # ---------- Lambda: process flagged transactions ----------
        processor = _lambda.Function(
            self, "FraudProcessor",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="handler.handler",
            code=_lambda.Code.from_asset(os.path.join(ROOT, "lambda_fn")),
            timeout=Duration.seconds(30),
            environment={
                "FLAGGED_TABLE": flagged_table.table_name,
                "ALERT_TOPIC_ARN": topic.topic_arn,
            },
        )
        processor.add_event_source(
            event_sources.SqsEventSource(queue, batch_size=10, report_batch_item_failures=True)
        )
        flagged_table.grant_write_data(processor)
        topic.grant_publish(processor)

        # ---------- ECS Fargate API behind an ALB ----------
        # public subnets only and no NAT gateway, since NAT costs about $1 a day for a demo
        # the load balancer is the only thing open to the internet, the api tasks only accept traffic from it
        vpc = ec2.Vpc(
            self, "Vpc",
            max_azs=2,
            nat_gateways=0,
            subnet_configuration=[
                ec2.SubnetConfiguration(name="public", subnet_type=ec2.SubnetType.PUBLIC, cidr_mask=24)
            ],
        )

        service = ecs_patterns.ApplicationLoadBalancedFargateService(
            self, "ApiService",
            vpc=vpc,
            cpu=256,
            memory_limit_mib=512,
            desired_count=1,
            public_load_balancer=True,
            assign_public_ip=True,  # needed to pull the image and reach aws without a NAT
            task_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            task_image_options=ecs_patterns.ApplicationLoadBalancedTaskImageOptions(
                image=ecs.ContainerImage.from_asset(
                    os.path.join(ROOT, "api"),
                    platform=ecr_assets.Platform.LINUX_AMD64,  # what fargate runs, matters on apple silicon
                ),
                container_port=8000,
                environment={
                    "STORAGE_BACKEND": "dynamodb",
                    "QUEUE_BACKEND": "sqs",
                    "TRANSACTIONS_TABLE": transactions_table.table_name,
                    "LOGIN_ATTEMPTS_TABLE": login_attempts_table.table_name,
                    "FLAGGED_QUEUE_URL": queue.queue_url,
                },
            ),
        )
        service.target_group.configure_health_check(path="/health")

        # least privilege, the api can only touch what it needs
        transactions_table.grant_read_write_data(service.task_definition.task_role)
        login_attempts_table.grant_read_write_data(service.task_definition.task_role)
        queue.grant_send_messages(service.task_definition.task_role)

        # ---------- Bonus: alarm when fraud volume spikes ----------
        spike_alarm = cloudwatch.Alarm(
            self, "FraudSpikeAlarm",
            metric=queue.metric_number_of_messages_sent(period=Duration.minutes(5), statistic="Sum"),
            threshold=10,
            evaluation_periods=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            alarm_description="10+ flagged transactions in 5 minutes",
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        spike_alarm.add_alarm_action(cw_actions.SnsAction(topic))

        CfnOutput(self, "ApiUrl", value=f"http://{service.load_balancer.load_balancer_dns_name}")
        CfnOutput(self, "FlaggedTableName", value=flagged_table.table_name)
