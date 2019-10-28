resource "aws_cloudwatch_event_rule" "schedule" {
  name                = "event-generator-for-aws-limits"
  schedule_expression = "cron(${var.cron})"
}

resource "aws_cloudwatch_event_target" "sns" {
  arn  = aws_lambda_function.scrape_limits.arn
  rule = aws_cloudwatch_event_rule.schedule.name
}