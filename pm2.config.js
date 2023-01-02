// this means if app restart {MAX_RESTART} times in 1 min then it stops
const NODE_ENV = process.env.NODE_ENV || 'development';
const INTERPRETER = process.env.POOLER_INTERPRETER || "python";

const MAX_RESTART = 10;
const MIN_UPTIME = 60000;


module.exports = {
  apps : [
    {
      name   : "pooler-process-hub-core",
      script : `${INTERPRETER} -m pooler.launch_process_hub_core`,
      max_restarts: MAX_RESTART,
      min_uptime: MIN_UPTIME,
      env: {
        NODE_ENV: NODE_ENV,
      }
    },
    {
      name   : "pooler-core-api",
      script : `${INTERPRETER} -m pooler.gunicorn_core_launcher`,
      max_restarts: MAX_RESTART,
      min_uptime: MIN_UPTIME,
      env: {
        NODE_ENV: NODE_ENV,
      }
    }
  ]
}
