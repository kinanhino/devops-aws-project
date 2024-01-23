import boto3
import os
from time import sleep
from loguru import logger

region = os.environ['REGION']

def metric_streamer():

    sqs_client = boto3.resource('sqs', region_name=region)
    asg_client = boto3.client('autoscaling', region_name=region)

    AUTOSCALING_GROUP_NAME = os.environ['AGN']
    QUEUE_NAME = os.environ['QUEUE_NAME']

    queue = sqs_client.get_queue_by_name(QueueName=QUEUE_NAME)
    msgs_in_queue = int(queue.attributes.get('ApproximateNumberOfMessages'))
    asg_groups = asg_client.describe_auto_scaling_groups(AutoScalingGroupNames=[AUTOSCALING_GROUP_NAME])[
        'AutoScalingGroups']

    if not asg_groups:
        raise RuntimeError('Autoscaling group not found')
    else:
        asg_size = asg_groups[0]['DesiredCapacity']
    if asg_size == 0:
        asg_size = 1
    backlog_per_instance = msgs_in_queue / asg_size

    # send backlog_per_instance to cloudwatch
    cloudwatch_client = boto3.client('cloudwatch', region_name=region)
    cloudwatch_client.put_metric_data(
        Namespace='KinanNamespace',  # Replace with your desired namespace
        MetricData=[
            {
                'MetricName': 'BacklogPerInstance',
                'Dimensions': [
                    {
                        'Name': 'AutoScalingGroupName',
                        'Value': AUTOSCALING_GROUP_NAME
                    },
                ],
                'Unit': 'Count',
                'Value': backlog_per_instance
            },
        ]
    )

    return_json = {
        'statusCode': 200,
        'body': f'Successfully sent backlog_per_instance metric: {backlog_per_instance}'
    }
    logger.info(return_json)
    return return_json


while True:
    metric_streamer()
    sleep(2)
