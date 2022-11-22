
// this means if app restart {MAX_RESTART} times in 1 min then it stops
const MAX_RESTART = 10;
const MIN_UPTIME = 60000; 
const NODE_ENV = "production" // process.env.NODE_ENV || 'development';
const CWD = "<>"

module.exports = {
  apps : [
    {
      name   : "pooler-core-api",
      script : "python3 ./gunicorn_core_launcher.py",
      max_restarts: MAX_RESTART,
      min_uptime: MIN_UPTIME,
      env: {
        NODE_ENV: NODE_ENV,
      }
    },
    {
      name   : "pooler-adapter-central-logging",
      script : "python3 ./proto_system_logging_server.py",
      max_restarts: MAX_RESTART,
      min_uptime: MIN_UPTIME,
      env: {
        NODE_ENV: NODE_ENV,
      }
    },
    {
      name   : "token-data-collator",
      script : "./uniswapTokenData",
      cwd : CWD+"uniswap-token-data-collator"
      max_restarts: MAX_RESTART,
      env: {
        NODE_ENV: NODE_ENV,
      },
      args: "5"
    },
  ]
}
