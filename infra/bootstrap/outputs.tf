output "backend_bucket" { value = aws_s3_bucket.state.id }

output "plan_role" { value = try(aws_iam_role.github["plan"].arn, null) }

output "apply_role" { value = try(aws_iam_role.github["apply"].arn, null) }
