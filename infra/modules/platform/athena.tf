resource "aws_athena_workgroup" "demo" {
  name          = local.name
  force_destroy = false
  configuration {
    enforce_workgroup_configuration    = true
    bytes_scanned_cutoff_per_query     = 10485760
    publish_cloudwatch_metrics_enabled = true
    result_configuration {
      output_location = "s3://${aws_s3_bucket.data["queries"].id}/results/"
      encryption_configuration {
        encryption_option = "SSE_S3"
      }
    }
  }
}
