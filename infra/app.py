import aws_cdk as cdk

from stack import FraudStack

app = cdk.App()
FraudStack(
    app,
    "FraudDetectionStack",
    # pass with: cdk deploy -c alert_email=you@example.com
    alert_email=app.node.try_get_context("alert_email"),
)
app.synth()
