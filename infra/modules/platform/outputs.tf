output "api_url" {
  value = aws_apigatewayv2_api.main.api_endpoint
}

output "dashboard_url" { value = "https://${aws_cloudfront_distribution.web.domain_name}" }

output "lake_bucket" {
  value = aws_s3_bucket.data["lake"].id
}

output "table_name" {
  value = aws_dynamodb_table.state.name
}
