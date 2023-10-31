import sys
from functools import wraps

from pooler.utils.default_logger import logger

# setup logging
logger = logger.bind(module="PowerLoom|HelperFunctions")


def cleanup_children_procs(fn):
    @wraps(fn)
    def wrapper(self, *args, **kwargs):
        try:
            fn(self, *args, **kwargs)
            logger.info("Finished running process hub core...")
        except Exception as e:
            logger.opt(exception=True).error(
                "Received an exception on process hub core run(): {}",
                e,
            )
            # logger.error('Initiating kill children....')
            # # silently kill all children
            # procs = psutil.Process().children()
            # for p in procs:
            #     p.terminate()
            # gone, alive = psutil.wait_procs(procs, timeout=3)
            # for p in alive:
            #     logger.error(f'killing process: {p.name()}')
            #     p.kill()
            logger.error("Waiting on spawned callback workers to join...")
            for (
                worker_class_name,
                unique_worker_entries,
            ) in self._spawned_cb_processes_map.items():
                for (
                    worker_unique_id,
                    worker_unique_process_details,
                ) in unique_worker_entries.items():
                    if worker_unique_process_details["process"].pid:
                        logger.error(
                            (
                                "Waiting on spawned callback worker {} | Unique"
                                " ID {} | PID {}  to join..."
                            ),
                            worker_class_name,
                            worker_unique_id,
                            worker_unique_process_details["process"].pid,
                        )
                        worker_unique_process_details["process"].join()

            logger.error(
                "Waiting on spawned core workers to join... {}",
                self._spawned_processes_map,
            )
            for (
                worker_class_name,
                unique_worker_entries,
            ) in self._spawned_processes_map.items():
                logger.error(
                    "spawned Process Pid to wait on {}",
                    unique_worker_entries.pid,
                )
                # internal state reporter might set proc_id_map[k] = -1
                if unique_worker_entries != -1:
                    logger.error(
                        ("Waiting on spawned core worker {} | PID {}  to" " join..."),
                        worker_class_name,
                        unique_worker_entries.pid,
                    )
                    unique_worker_entries.join()
            logger.error("Finished waiting for all children...now can exit.")
        finally:
            logger.error("Finished waiting for all children...now can exit.")
            self._reporter_thread.join()
            sys.exit(0)
            # sys.exit(0)

    return wrapper


def acquire_threading_semaphore(fn):
    @wraps(fn)
    def semaphore_wrapper(*args, **kwargs):
        semaphore = kwargs["semaphore"]

        logger.debug("Acquiring threading semaphore")
        semaphore.acquire()
        try:
            resp = fn(*args, **kwargs)
        except Exception:
            raise
        finally:
            semaphore.release()

        return resp

    return semaphore_wrapper


# # # END: placeholder for supporting liquidity events
