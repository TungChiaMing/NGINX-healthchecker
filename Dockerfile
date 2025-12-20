FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    python3.11 python3.11-venv python3-pip \
    iptables \
    iproute2 \
    net-tools \
    curl \
    vim \
    tcpdump \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/healthchecker


COPY project project

WORKDIR /opt/healthchecker/project

RUN python3 -m pip install --no-cache-dir uvicorn fastapi -r requirements.txt

WORKDIR /opt/healthchecker
EXPOSE 8082
