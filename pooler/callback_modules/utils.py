import os
import time
from functools import wraps

from pooler.settings.config import settings
from pooler.utils.default_logger import logger
from pooler.utils.models.data_models import SnapshotterIssue
from pooler.utils.models.data_models import SnapshotterIssueSeverity
from pooler.utils.models.message_models import PowerloomCallbackProcessMessage


SETTINGS_ENV = os.getenv('ENV_FOR_DYNACONF', 'development')


def notify_on_task_failure(fn):
    @wraps(fn)
    async def wrapper(self, *args, **kwargs):
        try:
            await fn(self, *args, **kwargs)

        except Exception as e:
            # Logging the error trace
            logger.opt(exception=True).error(f'Error: {e}')

            # Sending the error details to the issue reporting service
            try:
                if 'msg_obj' in kwargs:
                    msg_obj = kwargs['msg_obj']
                    if isinstance(msg_obj, PowerloomCallbackProcessMessage):
                        contract = msg_obj.contract
                        project_id = f'uniswap_pairContract_*_{contract}_{settings.namespace}'

                await self._client.post(
                    url=settings.issue_report_url,
                    json=SnapshotterIssue(
                        instanceID=settings.instance_id,
                        severity=SnapshotterIssueSeverity.medium,
                        issueType='MISSED_SNAPSHOT',
                        projectID=project_id if project_id else '*',
                        timeOfReporting=int(time.time()),
                        extra={'issueDetails': f'Error : {e}'},
                        serviceName='Pooler|PairTotalReservesProcessor',
                    ).dict(),
                )
            except Exception as err:
                # Logging the error trace if service is not able to report issue
                logger.opt(exception=True).error(f'Error: {err}')

    return wrapper
