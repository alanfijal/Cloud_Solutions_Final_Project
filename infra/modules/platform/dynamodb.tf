resource "aws_dynamodb_table" "state" {
  name         = local.name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"
  attribute {
    name = "pk"
    type = "S"
  }
  stream_enabled   = true
  stream_view_type = "NEW_IMAGE"
  server_side_encryption {
    enabled = true
  }
  ttl {
    attribute_name = "ttl"
    enabled        = true
  }
}
