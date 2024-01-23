import time
from pathlib import Path

from botocore.exceptions import ClientError
from detect import run
import yaml
from loguru import logger
import os
import boto3
from decimal import Decimal
import requests

region = os.getenv('REGION')
images_bucket = os.environ['BUCKET_NAME']
queue_name = os.environ['SQS_QUEUE_NAME']
alb_url = os.environ['ALB_URL']
session = boto3.Session(region_name=region)

sqs_client = session.client('sqs')

with open("data/coco128.yaml", "r") as stream:
    names = yaml.safe_load(stream)['names']

def consume():
    while True:
        response = sqs_client.receive_message(QueueUrl=queue_name, MaxNumberOfMessages=1, WaitTimeSeconds=5)

        if 'Messages' in response:
            message = response['Messages'][0]['Body']
            receipt_handle = response['Messages'][0]['ReceiptHandle']
            # Use the ReceiptHandle as a prediction UUID
            prediction_id = response['Messages'][0]['MessageId']

            logger.info(f'prediction: {prediction_id}. start processing')
            message = message.split(',')
            logger.info(f'message: {message}')
            # Receives a URL parameter representing the image to download from S3
            img_name = message[0]
            chat_id = message[1]
            local_path = img_name.split("/")[-1]
            original_img_path = download_image_from_s3(images_bucket,img_name,local_path)

            logger.info(f'prediction: {prediction_id}/{original_img_path}. Download img completed')

            # Predicts the objects in the image
            run(
                weights='yolov5s.pt',
                data='data/coco128.yaml',
                source=original_img_path,
                project='static/data',
                name=prediction_id,
                save_txt=True
            )

            logger.info(f'prediction: {prediction_id}/{original_img_path}. done')

            # This is the path for the predicted image with labels
            # The predicted image typically includes bounding boxes drawn around the detected objects, along with class labels and possibly confidence scores.
            predicted_img_path = Path(f'static/data/{prediction_id}/{original_img_path}')

            prediction_s3_path = f'predicted/{original_img_path}'
            upload_file_to_s3(predicted_img_path, images_bucket, prediction_s3_path)
            # Parse prediction labels and create a summary
            pred_summary_path = Path(f'static/data/{prediction_id}/labels/{original_img_path.split(".")[0]}.txt')
            if pred_summary_path.exists():
                with open(pred_summary_path) as f:
                    labels = f.read().splitlines()
                    labels = [line.split(' ') for line in labels]
                    labels_done = [{
                        'class': names[int(l[0])],
                        'cx': Decimal(str(l[1])),
                        'cy': Decimal(str(l[2])),
                        'width': Decimal(str(l[3])),
                        'height': Decimal(str(l[4])),
                    } for l in labels]

                logger.info(f'prediction: {prediction_id}/{original_img_path}. prediction summary:\n\n{labels_done}')

                prediction_summary = {
                    'prediction_id': prediction_id,
                    'original_img_path': original_img_path,
                    'predicted_img_path': str(predicted_img_path),
                    'chat_id': chat_id,
                    'labels': labels_done,
                    'time': Decimal(time.time())
                }
                # store the prediction_summary in a DynamoDB table
                dynamo_res = store_dynamo(prediction_summary)
	        # perform a GET request to Polybot to `/results` endpoint
                send_request_to_polybot(prediction_id)
            # Delete the message from the queue as the job is considered as DONE
            sqs_client.delete_message(QueueUrl=queue_name, ReceiptHandle=receipt_handle)

def send_request_to_polybot(prediction_id):
    try:
        cert_path = 'YOURPUBLIC.pem'
        res = requests.get(f'{alb_url}/results?predictionId={prediction_id}', verify=False)
        logger.info(f'Status Code: {res.status_code}')
        res.raise_for_status()
        return 'OK'
    except requests.exceptions.HTTPError as http_err:
        logger.error(f"HTTP error occurred: {http_err}")
    except Exception as e:
        logger.error(f"An error occurred: {e}")

def upload_file_to_s3(file_name, bucket, object_name=None):
    if object_name is None:
        object_name = file_name
    s3_client = session.client('s3')
    try:
        s3_client.upload_file(file_name, bucket, object_name)
    except ClientError as e:
        logger.error(e)
        return False
    return True

def download_image_from_s3(bucket, s3_img_path, local_img_path=None):
    if local_img_path is None:
        local_img_path = s3_img_path
    s3_client = session.client('s3')
    try:
        s3_client.download_file(bucket, s3_img_path, local_img_path)
        logger.info(f'downloaded successfully to {local_img_path}')
    except Exception as e:
        logger.error(f'Error downloading image from S3:{e}')
        return None
    return local_img_path

def store_dynamo(summary_dictionary):
    dynamodb = session.resource('dynamodb')
    dynamo_tbl = dynamodb.Table('aws-dynamo-kinan')
    try:
        res = dynamo_tbl.put_item(Item=summary_dictionary)
        logger.info(f'Saved successfully to DynamoDB')
        return res
    except Exception as e:
        logger.error(f"Error adding item to DynamoDB: {e}")
        return None

if __name__ == "__main__":
    consume()
