FROM nikolaik/python-nodejs:python3.9-nodejs18-bullseye
RUN python -v
RUN pip -v
RUN node -v
RUN npm install pm2 -g
RUN pm2 ls
COPY poetry.lock .
COPY pyproject.toml .
RUN poetry install
EXPOSE 8002
#EXPOSE 9090
COPY . .
#RUN poetry run python -m pooler.init_rabbitmq
CMD chmod +x ./init_processes.sh
#RUN pm2 start pm2.config.js && pm2 logs --lines 100
#RUN ./init_processes.sh
