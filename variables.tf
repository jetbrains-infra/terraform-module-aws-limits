variable "ALARM_ACTIONS" {
  type    = list(string)
  default = []
}

variable "cron" {
  default = "*/10 * * * ? *"
}

variable "config" {
  default = <<EOF
# Trusted Advisor refresh params
# https://awslimitchecker.readthedocs.io/en/latest/python_usage.html#refreshing-trusted-advisor-check-results
ta_refresh_mode: 21600
ta_refresh_timeout: 1800

# Services
# Required:
#  * service.name
#  * limit.name
#  * limit.value
# Optional: all other
#services:
#- name: EC2
#  limits:
#  - name: 'Elastic IP addresses (EIPs)'
#    value: 5
#    warn_percent: 50
#    crit_percent: 75
#    warn_count: 2
#    crit_count: 1
#    override_ta: false

# Don't check services below
#skip:
#  - Firehose
EOF
}