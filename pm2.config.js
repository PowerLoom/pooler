// this means if app restart {MAX_RESTART} times in 1 min then it stops
const NODE_ENV = process.env.NODE_ENV || 'development';
const INTERPRETER = process.env.POOLER_INTERPRETER || "python";
const START_BLOCK = process.env.POOLER_LAST_BLOCK || 16175073;

const MAX_RESTART = 10;
const MIN_UPTIME = 60000;


module.exports = {
  apps : [
    {
      name   : "pooler-process-hub-core",
      script : `${INTERPRETER} ${__dirname}/launch_process_hub_core.py`,
      max_restarts: MAX_RESTART,
      min_uptime: MIN_UPTIME,
      env: {
        NODE_ENV: NODE_ENV,
      }
    },
    {
      name   : "pooler-core-api",
      script : `${INTERPRETER} ${__dirname}/gunicorn_core_launcher.py`,
      max_restarts: MAX_RESTART,
      min_uptime: MIN_UPTIME,
      env: {
        NODE_ENV: NODE_ENV,
      }
    },
    {
      name   : "pooler-adapter-central-logging",
      script : `${INTERPRETER} ${__dirname}/proto_system_logging_server.py`,
      max_restarts: MAX_RESTART,
      min_uptime: MIN_UPTIME,
      env: {
        NODE_ENV: NODE_ENV,
      }
    },
    {
      name   : "pooler-epoch-detector",
      script : `${INTERPRETER} ${__dirname}/system_epoch_detector.py`,
      max_restarts: MAX_RESTART,
      min_uptime: MIN_UPTIME,
      env: {
        NODE_ENV: NODE_ENV,
      }
    },
    {
      name   : "pooler-init-processes",
      script : `bash ${__dirname}/init_processes.sh ${START_BLOCK}`,
      max_restarts: 1,
      min_uptime: MIN_UPTIME,
      auto_restart: false,
      env: {
        NODE_ENV: NODE_ENV,
      }
    }
    
  ]
}
