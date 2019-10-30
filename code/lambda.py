import os
import sys
import yaml
import base64
import io
from typing import List
from awslimitchecker.checker import AwsLimitChecker
from awslimitchecker.limit import AwsLimitUsage
from awslimitchecker.limit import AwsLimit
import boto3

import logging


logging.basicConfig(level=os.environ.get('LOG_LEVEL', logging.INFO))
log = logging.getLogger(__name__)

CONFIG_NAME = 'config.yaml'
METRICS_NAMESPACE = 'ServicesLimits'


class InvalidObjectInConfig(Exception):
    pass


class Limit:
    name: str
    service_name: str
    value: int
    warn_percent: int
    crit_percent: int
    warn_count: int
    crit_count: int
    override_ta: bool

    def __init__(self, service_name, data):
        self.name = data.get('name')
        self.value = data.get('value')
        self.service_name = service_name
        self.warn_percent = data.get('warn_percent')
        self.crit_percent = data.get('crit_percent')
        self.warn_count = data.get('warn_count')
        self.crit_count = data.get('crit_count')
        self.override_ta = data.get('override_ta', False)
        if self.name is None:
            raise InvalidObjectInConfig('Limit must have name')
        if self.service_name is None:
            raise InvalidObjectInConfig('Limit must have service_name')
        if self.value is None:
            raise InvalidObjectInConfig('Limit must have value')

    def __str__(self):
        return f'Limit("{self.service_name}", "{self.name}", value:"{self.value}", warn:"{self.warn_percent} %", ' \
               f'crit:"{self.crit_percent} %", ' \
               f'warn_count: "{self.warn_count}", crit_count:"{self.crit_count}")'

    def override(self, checker: AwsLimitChecker):
        log.info(f'Overriding limits for {self}')
        checker.set_limit_override(self.service_name,
                                   self.name,
                                   self.value,
                                   override_ta=self.override_ta)

        overrides = ['warn_percent', 'crit_percent', 'warn_count', 'crit_count']
        params = {}
        for field in overrides:
            value = getattr(self, field)
            if value is not None:
                params[field] = value

        log.info(f'Overriding threshold for {self}')
        if self.warn_percent is not None and self.crit_percent is not None:
            checker.set_threshold_override(self.service_name, self.name, **params)


class Metric:
    metric_name: str
    dimensions: []
    value: float

    def __init__(self, limit: AwsLimit, usage: AwsLimitUsage):
        self.metric_name = f'{limit.service.service_name}-{limit.name}'
        self.dimensions = []
        if usage.aws_type is not None:
            self.dimensions.append({'Name': 'aws_type', 'Value': usage.aws_type})
        if usage.resource_id is not None:
            self.dimensions.append({'Name': 'resource_id', 'Value': usage.resource_id})
        self.value = usage.value

    def get_data(self):
        return {
            'MetricName': self.metric_name,
            'Dimensions': self.dimensions,
            'Values': [self.value]
        }


class Alarm:
    alarm_name: str
    metric_name: str
    period: int
    evaluation_period_sec: int
    threshold: float
    alarm_actions: List[str]
    dimensions: list

    def __init__(self, limit: AwsLimit, type: str, dimensions: list, alarm_actions: List[str] = []):
        self.alarm_name = f'{limit.service.service_name} {limit.name} {type}'
        self.metric_name = f'{limit.service.service_name} {limit.name}'
        self.alarm_actions = alarm_actions
        self.period = 3600  # 1h
        self.evaluation_period_sec = 4  # 4h
        self.dimensions = dimensions

        resource_id = self.get_resource_id_from_dimensions()
        if resource_id is not None:
            self.alarm_name += ' ' + resource_id

        if type == 'warn':
            self.threshold = limit.get_limit() * (limit.warn_percent or limit.def_warning_threshold / 100)
        elif type == 'crit':
            self.threshold = limit.get_limit() * (limit.crit_percent or limit.def_critical_threshold / 100)
        else:
            raise Exception(f'Unknown type "{type}" for Alarm')

    def get_resource_id_from_dimensions(self):
        for dimension in self.dimensions:
            if dimension.get('Name', '') == 'resource_id':
                return dimension.get('Value')
        return None

    def get_data(self):
        return {
            'AlarmName': self.alarm_name,
            'MetricName': self.metric_name,
            'AlarmActions': self.alarm_actions,
            'Namespace': METRICS_NAMESPACE,
            'Statistic': 'Maximum',  # 'SampleCount' | 'Average' | 'Sum' | 'Minimum' | 'Maximum',
            'Period': self.period,
            'EvaluationPeriods': self.evaluation_period_sec,
            'Threshold': self.threshold,
            'ComparisonOperator': 'GreaterThanOrEqualToThreshold',
            'TreatMissingData': 'breaching',    # 'string', breaching | notBreaching | ignore | missing
            'Dimensions': self.dimensions,
            'Tags': [
                {'Key': 'generated-by', 'Value': 'terraform-module-aws-limits'},
            ]
        }


class CloudWatchClient:
    namespace: str
    max_batch: int

    def __init__(self, namespace):
        self.max_batch = 20
        self.namespace = namespace
        self.client = boto3.client('cloudwatch')

    def put_metric_data(self, metrics: [Metric]):
        """
        https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/cloudwatch.html#CloudWatch.Client.put_metric_data
        :param metrics: [Metric]
        :return: None
        """
        batch = []
        for metric in metrics:
            batch.append(metric.get_data())
            if len(batch) == self.max_batch:
                self._send_metrics(batch)
                batch = []
        if len(batch) != 0:
            self._send_metrics(batch)

    def put_metric_alarms(self, alarms: [Alarm]):
        for alarm in alarms:
            self.client.put_metric_alarm(**alarm.get_data())

    def _send_metrics(self, batch):
        self.client.put_metric_data(Namespace=self.namespace, MetricData=batch)


def scrape_limits(event, context):
    data = base64.b64decode(os.environ.get('CONFIG_DATA_BASE64'))
    fd = io.StringIO(data.decode('utf-8'))
    config = yaml.safe_load(fd)
    if config is None:
        log.error(f'Unable to read configuration file "{CONFIG_NAME}" exiting...')
        sys.exit(1)
    alarm_actions = os.environ.get('ALARM_ACTIONS', "").split(',')
    alarm_actions = list(filter(lambda a: a != '', alarm_actions))

    limits = []
    for service in config.get('services', []):
        for limit in service.get('limits', []):
            try:
                limits.append(Limit(service.get('name'), limit))
            except InvalidObjectInConfig as e:
                log.error(e)

    c = AwsLimitChecker(ta_refresh_mode=config.get('ta_refresh_mode', 21600),
                        ta_refresh_timeout=config.get('ta_refresh_timeout', 1800))
    for limit in limits:
        limit.override(c)

    c.remove_services(config.get('skip', []))

    cwc = CloudWatchClient(METRICS_NAMESPACE)

    metrics = []
    alarms = []
    results = c.get_limits()
    log.info('----------------------------------------------')
    for service, limits in results.items():
        for limit, value in limits.items():
            log.info(f'service={service} limit={limit} usage={value.get_current_usage_str()}')
            for usage in value.get_current_usage():
                metric = Metric(value, usage)
                metrics.append(metric)

                if not value.has_resource_limits():
                    log.warning(f'Limit {value.name} has no limit')
                else:
                    alarms.append(Alarm(value, 'warn', metric.dimensions, alarm_actions))
                    alarms.append(Alarm(value, 'crit', metric.dimensions, alarm_actions))

    cwc.put_metric_data(metrics)
    cwc.put_metric_alarms(alarms)

    return {
        'message': 'Done'
    }


if __name__ == '__main__':
    scrape_limits(None, None)
