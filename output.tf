# In outputs.tf
output "topic_name" {
  value = google_pubsub_topic.topic.name
}

output "function_url" {
  value = google_cloudfunctions2_function.function.name
}
