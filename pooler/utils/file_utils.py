import json
import os
from typing import Any
from typing import Optional

from loguru import logger


default_logger = logger.bind(module='PowerLoom|FileUtils')


def read_json_file(
    file_path: str,
    logger: logger = default_logger,
) -> Optional[dict]:
    """Read given json file and return its content as a dictionary."""
    try:
        f_ = open(file_path, 'r', encoding='utf-8')
    except Exception as exc:
        logger.warning(f'Unable to open the {file_path} file')
        logger.opt(exception=True).error(exc)
        raise exc
    else:
        json_data = json.loads(f_.read())
        return json_data


def write_json_file(
    directory: str,
    file_name: str,
    data: Any,
    logger: logger = logger,
) -> None:
    try:
        file_path = directory + file_name
        if not os.path.exists(directory):
            os.makedirs(directory)
        f_ = open(file_path, 'w', encoding='utf-8')
    except Exception as exc:
        logger.error(f'Unable to open the {file_path} file')
        raise exc
    else:
        json.dump(data, f_, ensure_ascii=False, indent=4)


def write_bytes_to_file(directory: str, file_name: str, data):
    try:
        file_path = directory + file_name
        if not os.path.exists(directory):
            os.makedirs(directory)
        file_obj = open(file_path, 'wb')
    except Exception as exc:
        logger.opt(exception=True).error('Unable to open the {} file', file_path)
        raise exc
    else:
        bytes_written = file_obj.write(data)
        logger.debug('Wrote {} bytes to file {}', bytes_written, file_path)
        file_obj.close()


def read_text_file(file_path: str):
    """Read given file and return the read bytes in form of a string."""
    try:
        file_obj = open(file_path, 'r', encoding='utf-8')
    except FileNotFoundError:
        return None
    except Exception as exc:
        logger.opt(exception=True).warning('Unable to open the {} file because of exception: {}', file_path, exc)
        return None
    else:
        return file_obj.read()
