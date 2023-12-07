import json
import logging
import os
import resource
import sys

from snapshotter.auth.conf import auth_settings
from snapshotter.auth.server_entry import app
from snapshotter.settings.config import settings
from snapshotter.utils.default_logger import FORMAT
from snapshotter.utils.default_logger import logger
from snapshotter.utils.gunicorn import InterceptHandler
from snapshotter.utils.gunicorn import StandaloneApplication
from snapshotter.utils.gunicorn import StubbedGunicornLogger

JSON_LOGS = True if os.environ.get('JSON_LOGS', '0') == '1' else False
LOG_LEVEL = logging.getLevelName(os.environ.get('LOG_LEVEL', 'DEBUG'))
WORKERS = len(auth_settings.signers)

# reset pid.json
with open('pid.json', 'w') as pid_file:
    json.dump([], pid_file)


def post_worker_init(worker):
    # add worker pid to a list and store that file
    with open('pid.json', 'r') as pid_file:
        data = json.load(pid_file)
        data.append(worker.pid)

    with open('pid.json', 'w') as pid_file:
        json.dump(data, pid_file)

    # print(worker.app.application.state.worker_id)
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    resource.setrlimit(
        resource.RLIMIT_NOFILE,
        (settings.rlimit.file_descriptors, hard),
    )


if __name__ == '__main__':
    intercept_handler = InterceptHandler()
    logging.root.setLevel(LOG_LEVEL)

    seen = set()
    for name in [
        *logging.root.manager.loggerDict.keys(),
        'gunicorn',
        'gunicorn.access',
        'gunicorn.error',
        'uvicorn',
        'uvicorn.access',
        'uvicorn.error',
    ]:
        if name not in seen:
            seen.add(name.split('.')[0])
            logging.getLogger(name).handlers = [intercept_handler]

    logger.add(sys.stdout, format=FORMAT, level=LOG_LEVEL, serialize=JSON_LOGS)
    logger.add(sys.stderr, format=FORMAT, level=logging.ERROR, serialize=JSON_LOGS)

    options = {
        'bind': f'{auth_settings.bind.host}:{auth_settings.bind.port}',
        'workers': WORKERS,
        'accesslog': '-',
        'errorlog': '-',
        'worker_class': 'uvicorn.workers.UvicornWorker',
        'logger_class': StubbedGunicornLogger,
        'post_worker_init': post_worker_init,
    }

    StandaloneApplication(app, options).run()
