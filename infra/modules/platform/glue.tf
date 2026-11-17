resource "aws_glue_catalog_database" "lake" {
  name = replace(local.name, "-", "_")
}

resource "aws_glue_catalog_table" "events" {
  database_name = aws_glue_catalog_database.lake.name
  name          = "events"
  table_type    = "EXTERNAL_TABLE"
  parameters = {
    EXTERNAL = "TRUE", classification = "json"
  }
  storage_descriptor {
    location      = "s3://${aws_s3_bucket.data["lake"].id}/raw/"
    input_format  = "org.apache.hadoop.mapred.TextInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat"
    ser_de_info {
      serialization_library = "org.openx.data.jsonserde.JsonSerDe"
    }
    dynamic "columns" {
      for_each = {
        event_id = "string", event_type = "string", unit_id = "string", reading_id = "string", incident_id = "string", observed_at = "string", temperature = "double", detail = "string"
      }
      content {
        name = columns.key
        type = columns.value
      }
    }
  }
}
