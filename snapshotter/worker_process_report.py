import json

import psutil
import redis

from snapshotter.settings.config import settings
from snapshotter.utils.redis.redis_conn import REDIS_CONN_CONF


def process_up(pid):
    """
    Check if a process with given PID is running or not.

    Args:
        pid (int): Process ID to check.

    Returns:
        bool: True if process is running, False otherwise.
    """
    p_ = psutil.Process(pid)
    return p_.is_running()
    # try:
    #     return os.waitpid(pid, os.WNOHANG) is not None
    # except ChildProcessError:  # no child processes
    #     return False
    # try:
    #     call = subprocess.check_output("pidof '{}'".format(self.processName), shell=True)
    #     return True
    # except subprocess.CalledProcessError:
    #     return False


def main():
    """
    Retrieves process details from Redis cache and prints their running status.

    Retrieves process details from Redis cache and prints their running status. The process details include the System Event
    Detector, Worker Processor Distributor, and Worker Processes. The running status of each process is determined using the
    `process_up` function.
    """
    connection_pool = redis.BlockingConnectionPool(**REDIS_CONN_CONF)
    redis_conn = redis.Redis(connection_pool=connection_pool)
    map_raw = redis_conn.hgetall(
        name=f'powerloom:snapshotter:{settings.namespace}:{settings.instance_id}:Processes',
    )
    event_det_pid = map_raw[b'SystemEventDetector']
    print('\n' + '=' * 20 + 'System Event Detector' + '=' * 20)
    try:
        event_det_pid = int(event_det_pid)
    except ValueError:
        print('Event detector pid found in process map not a PID: ', event_det_pid)
    else:
        # event_detector_proc = psutil.Process(event_det_pid)
        print('Event detector process running status: ', process_up(event_det_pid))

    print('\n' + '=' * 20 + 'Worker Processor Distributor' + '=' * 20)
    proc_dist_pid = map_raw[b'ProcessorDistributor']
    try:
        proc_dist_pid = int(proc_dist_pid)
    except ValueError:
        print('Processor distributor pid found in process map not a PID: ', proc_dist_pid)
    else:
        # proc_dist_proc = psutil.Process(proc_dist_pid)
        print('Processor distributor process running status: ', process_up(proc_dist_pid))

    print('\n' + '=' * 20 + 'Worker Processes' + '=' * 20)
    cb_worker_map = map_raw[b'callback_workers']
    try:
        cb_worker_map = json.loads(cb_worker_map)
    except json.JSONDecodeError:
        print('Callback worker entries in cache corrupted...', cb_worker_map)
        return
    for worker_type, worker_details in cb_worker_map.items():
        section_name = worker_type.capitalize()
        print('\n' + '*' * 10 + section_name + '*' * 10)
        if not worker_details or not isinstance(worker_details, dict):
            print(f'No {section_name} workers found in process map: ', worker_details)
            continue
        for short_id, worker_details in worker_details.items():
            print('\n' + '-' * 5 + short_id + '-' * 5)
            proc_pid = worker_details['pid']
            try:
                proc_pid = int(proc_pid)
            except ValueError:
                print(f'Process name {worker_details["id"]} pid found in process map not a PID: ', proc_pid)
            else:
                # proc = psutil.Process(proc_pid)
                print('Process name ' + worker_details['id'] + ' running status: ', process_up(proc_pid))


if __name__ == '__main__':
    main()
