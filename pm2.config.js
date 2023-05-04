// this means if app restart {MAX_RESTART} times in 1 min then it stops
const NODE_ENV = process.env.NODE_ENV || 'development';

const MAX_RESTART = 10;
const MIN_UPTIME = 60000;


module.exports = {
  apps : [
    {
      name   : "pooler-process-hub-core",
      script : `poetry run python -m pooler.launch_process_hub_core`,
      max_restarts: MAX_RESTART,
      min_uptime: MIN_UPTIME,
      env: {
        NODE_ENV: NODE_ENV,
      }
    },
    {
      name   : "pooler-core-api",
      script : `poetry run python -m pooler.gunicorn_core_launcher`,
      max_restarts: MAX_RESTART,
      min_uptime: MIN_UPTIME,
      env: {
        NODE_ENV: NODE_ENV,
      }
    },
    {
      name   : "ap-payload-commit",
      script : "go/payload-commit",
      cwd : `${__dirname}/go/payload-commit`,
      max_restarts: MAX_RESTART,
      min_uptime: MIN_UPTIME,
      kill_timeout : 3000,
      env: {
        NODE_ENV: NODE_ENV,
        CONFIG_PATH:`${__dirname}`,
      },
      args: "5" //Log level set to debug, for production change to 4 (INFO) or 2(ERROR)
    },
  ]
}
