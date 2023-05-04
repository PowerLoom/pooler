FROM golang:alpine3.17

ENV GO111MODULE=on

# Install python/pip
ENV PYTHONUNBUFFERED=1

RUN apk add --no-cache rust cargo

RUN apk add --update --no-cache python3-dev && ln -sf python3 /usr/bin/python
RUN python3 -m ensurepip
RUN pip3 install --no-cache --upgrade pip setuptools

RUN apk add --no-cache libffi-dev openssl-dev && \
    LDFLAGS="-L/usr/local/opt/openssl/lib" \
    CFLAGS="-I/usr/local/opt/openssl/include" \
    pip3 install --no-cache-dir cffi

# Install Poetry
RUN pip3 install poetry
# RUN curl -sSL https://install.python-poetry.org | python

# ENV POETRY_HOME="/root/.poetry"
# ENV PATH="$POETRY_HOME/bin:$PATH"

RUN apk update && apk add --no-cache ethtool nodejs npm bash build-base musl-dev libc-dev curl libffi-dev vim nano

# RUN apk update && apk add --no-cache ethtool nodejs npm bash gcc musl-dev libc-dev curl libffi-dev vim nano

RUN npm install pm2 -g
RUN pm2 install pm2-logrotate && pm2 set pm2-logrotate:compress true && pm2 set pm2-logrotate:retain 7

# Set the working directory
WORKDIR /src

# Copy the application's dependencies files
COPY poetry.lock pyproject.toml ./

# Install the Python dependencies
RUN poetry install --no-dev

# Copy the rest of the application's files
COPY . .

# Make the shell scripts executable
RUN chmod +x ./snapshotter_autofill.sh ./init_processes.sh

# Expose the port that the application will listen on
EXPOSE 8002

COPY go/go.mod go/go.sum ./
RUN go mod download

RUN chmod +x init_processes.sh snapshotter_autofill.sh

RUN chmod +x init_processes.sh snapshotter_autofill.sh build.sh

RUN ./build.sh
