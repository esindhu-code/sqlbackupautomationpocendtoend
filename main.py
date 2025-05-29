import os
import json
import logging
import time
import base64
from google.cloud import pubsub_v1, logging as cloud_logging
from googleapiclient import discovery
from datetime import datetime, timezone  # Import datetime and timezone

# Initialize Cloud Logging
cloud_logging.Client().setup_logging()

# Constants
PROJECT_ID = os.environ.get("PROJECT_ID", "default-project-id")
RETRY_LIMIT = 3  # Number of retry attempts for failed backups
ALERT_TOPIC = os.environ.get("ALERT_TOPIC", "default-alert-topic") # Pub/Sub alert topic

def get_sql_admin_service():
    """Create Cloud SQL Admin API service client."""
    return discovery.build('sqladmin', 'v1beta4')

def initiate_backup(instance_id):
    """Start a backup for the Cloud SQL instance."""
    try:
        service = get_sql_admin_service()
        # Generate a human-readable description
        backup_description = f"Automated backup - {datetime.now(timezone.utc).strftime('%b %d, %Y, %I:%M:%S %p %Z')}"
        request = service.backupRuns().insert(
            project=PROJECT_ID,
            instance=instance_id,
            body={
                "description": backup_description
            }
        )
        response = request.execute()
        operation_name = response.get("name", "Unknown")
        logging.info(f"Backup initiated for instance: {instance_id}. Operation: {operation_name}")
        return operation_name
    except Exception as e:
        logging.error(f"Failed to initiate backup for {instance_id}: {e}")
        raise

def check_backup_status(operation_name, instance_id):
    """Verify backup operation status."""
    try:
        service = get_sql_admin_service()
        request = service.operations().get(
            project=PROJECT_ID,
            operation=operation_name
        )
        operation = request.execute()
        status = operation.get("status")
        error = operation.get("error", None)
        return status == "DONE", error
    except Exception as e:
        logging.error(f"Error checking backup status: {e}")
        raise

def publish_alert(message):
    """Send an alert to Pub/Sub topic."""
    try:
        publisher = pubsub_v1.PublisherClient()
        publisher.publish(ALERT_TOPIC, json.dumps(message).encode("utf-8"))
        logging.info(f"Published alert message: {message}")
    except Exception as e:
        logging.error(f"Failed to publish alert: {e}")

def retry_backup(instance_id):
    """Attempt backup retry with exponential backoff."""
    attempt = 0
    while attempt < RETRY_LIMIT:
        try:
            operation_name = initiate_backup(instance_id)
            time.sleep(2 ** attempt)  # Exponential backoff
            success, error = check_backup_status(operation_name, instance_id)
            if success:
                logging.info(f"Backup successful on retry {attempt + 1} for {instance_id}")
                return True
            else:
                logging.warning(f"Retry {attempt + 1} failed: {error}")
                attempt += 1
        except Exception as e:
            logging.error(f"Retry {attempt + 1} error: {e}")
            attempt += 1
    logging.error(f"Backup failed after {RETRY_LIMIT} retries for {instance_id}")
    return False

def process_pubsub_message(event, context):
    """Triggered by Pub/Sub, processes a backup request."""
    try:
        pubsub_message = json.loads(base64.b64decode(event["data"]).decode("utf-8"))
        instance_id = pubsub_message.get("instance_id")

        if not instance_id:
            raise ValueError("Missing 'instance_id' in Pub/Sub message.")

        operation_name = initiate_backup(instance_id)
        success, error = check_backup_status(operation_name, instance_id)

        if success:
            logging.info(f"Backup succeeded for instance: {instance_id}")
        else:
            logging.warning(f"Backup failed for instance: {instance_id}. Error: {error}")
            if not retry_backup(instance_id):
                alert_message = {
                    "instance_id": instance_id,
                    "error": str(error),
                    "timestamp": time.time()
                }
                publish_alert(alert_message)
    except Exception as e:
        logging.error(f"Error processing Pub/Sub message: {e}")
