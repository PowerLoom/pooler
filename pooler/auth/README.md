## Intro
 This module is mostly used to manage users and API keys using Redis (might be moved out in the future).
 There are several components in this module. Let's talk about them one by one.

### Settings and Config

#### Config JSON
The primary config for this module is defined in `auth_settings.json`. To help users get started, a boilerplate is provided in `auth_settings.example.json` which can be used to generate their own `auth_settings.json`.

The current settings structure is something like this

```json
{
  "redis": {
      "host": <host>,
      "port": <port>,
      "db": <db>,
      "password": <password>
    },
  "bind": {
    "host": <bind_host>,
    "port": <bind_port>
  }
}
```
The `redis` part of the config is used to configure the Redis instance that will be used to connect as the primary datastore.
The `bind` part of the config is used to configure the `host` and `port` where the API server will run.

#### Setting Models
The config JSON structure above is not entirely flexible. Everything from the auth_settings.json is loaded in well-defined `Settings Models` defined in `settings_models.py` using `conf.py`.
If any new config needs to be added, users must update the Setting Models first. This will make sure we always have a proper and updated data model for app configuration.

### Redis Utilities
`redis_conn.py` contains utility and helper functions for Redis pool setup and `redis_keys.py` contains functions to generate all the `keys` that are used in Redis across the entire module.

### Server

The main FastAPI server and entry point for this module is `server_entry.py`, this server is started using a custom Gunicorn handler present in `gunicorn_auth_entry_launcher.py`. Doing so provides more flexibility to customize the application and start it using `Pm2`.

### Helpers
All the other helper functions and utilities are present in `helpers.py`.
