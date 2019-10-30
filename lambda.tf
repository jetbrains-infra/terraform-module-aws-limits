resource "aws_lambda_function" "scrape_limits" {
  function_name    = "aws-limits-checker-scrape-limits"
  handler          = "lambda.scrape_limits"
  role             = aws_iam_role.aws_limit_checker.arn
  runtime          = "python3.7"
  filename         = "${path.module}/code/lambda.zip"
  source_code_hash = filebase64sha256("${path.module}/code/lambda.zip")
  timeout          = 900
  environment {
    variables = {
      ALARM_ACTIONS      = join(",", var.ALARM_ACTIONS)
      CONFIG_DATA_BASE64 = base64encode(var.config)
    }
  }
}

resource "aws_lambda_permission" "cw_scheduled_events" {
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.scrape_limits.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.schedule.arn
}
