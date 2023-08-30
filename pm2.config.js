// this means if app restart {MAX_RESTART} times in 1 min then it stops
const NODE_ENV = process.env.NODE_ENV || 'development';

const MAX_RESTART = 10;
const MIN_UPTIME = 60000;


module.exports = {
  apps : [
    {
      name   : "process-hub-core",
      script : `poetry run python -m snapshotter.launch_process_hub_core`,
      max_restarts: MAX_RESTART,
      min_uptime: MIN_UPTIME,
      error_file: "/dev/null",
      out_file: "/dev/null",
      env: {
        NODE_ENV: NODE_ENV,
      }
    },
    {
      name   : "core-api",
      script : `poetry run python -m snapshotter.gunicorn_core_launcher`,
      max_restarts: MAX_RESTART,
      min_uptime: MIN_UPTIME,
      error_file: "/dev/null",
      out_file: "/dev/null",
      env: {
        NODE_ENV: NODE_ENV,
        GUNICORN_WORKERS: 1,
      }
    },
    {
      name   : "auth-api",
      script : `poetry run python -m snapshotter.auth.gunicorn_auth_entry_launcher`,
      max_restarts: MAX_RESTART,
      min_uptime: MIN_UPTIME,
      error_file: "/dev/null",
      out_file: "/dev/null",
      env: {
        NODE_ENV: NODE_ENV,
        GUNICORN_WORKERS: 1,
      }
    }
  ]
}
