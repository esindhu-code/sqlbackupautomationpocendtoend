resource "google_pubsub_topic" "topic" {
  name = var.topic_name
}

resource "random_id" "bucket_suffix" {
  byte_length = 4 # Default value of bucket_suffix_byte_length
}

data "archive_file" "function_zip" {
  type        = "zip"
  source_dir  = "${path.module}/function_source"
  output_path = "${path.module}/function_source/function.zip"
}

resource "google_storage_bucket" "function_source" {
  name          = "${var.bucket_name}-${random_id.bucket_suffix.hex}-source"
  location      = var.region
  force_destroy = true
  uniform_bucket_level_access = true
}

resource "google_storage_bucket_object" "function_zip" {
  name   = var.object_name
  bucket = google_storage_bucket.function_source.name
  source = data.archive_file.function_zip.output_path
}

resource "google_cloudfunctions2_function" "function" {
  name        = var.function_name
  location    = var.region
  project     = var.project_id
  description = "Cloud Function triggered by Pub/Sub"

  build_config {
    runtime     = var.runtime
    entry_point = var.entry_point
    source {
      storage_source {
        bucket = google_storage_bucket.function_source.name
        object = google_storage_bucket_object.function_zip.name
      }
    }
  }

  service_config {
    max_instance_count    = 1 # Default value
    min_instance_count    = 0 # Default value
    available_memory      = "256M" # Default value
    timeout_seconds       = tonumber(regex("\\d+", var.timeout)) # Assumes timeout like "540s"
    service_account_email = var.service_account_email
    ingress_settings      = "ALLOW_INTERNAL_ONLY" # Default value
  }

  event_trigger {
    event_type     = "google.cloud.pubsub.topic.v1.messagePublished"
    pubsub_topic   = google_pubsub_topic.topic.id
    trigger_region = var.region
    retry_policy   = "RETRY_POLICY_RETRY" # Default value
  }
}

resource "google_cloud_scheduler_job" "job" {
  name      = var.scheduler_job_name
  schedule  = var.schedule
  time_zone = var.time_zone
  region    = var.region

  pubsub_target {
    topic_name = google_pubsub_topic.topic.id
    data       = base64encode(jsonencode({
      message     = var.message
      instance_id = var.instance_id
    }))
  }
}
