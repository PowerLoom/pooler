import json
import os
import logging

def read_json_file(file_path: str, logger = logging):
    """Read given json file and return its content as a dictionary."""
    try:
        f_ = open(file_path, 'r', encoding='utf-8')
    except Exception as exc:
        logger.warning(f"Unable to open the {file_path} file")
        logger.error(exc, exc_info=True)
        raise exc
    else:
        json_data = json.loads(f_.read())
        return json_data


def write_json_file(directory:str, file_name: str, data, logger):
    try:
        file_path = directory + file_name
        if not os.path.exists(directory):
            os.makedirs(directory)
        f_ = open(file_path, 'w', encoding='utf-8')
    except Exception as exc:
        logger.error(f"Unable to open the {file_path} file")
        raise exc
    else:
        json.dump(data, f_, ensure_ascii=False, indent=4)