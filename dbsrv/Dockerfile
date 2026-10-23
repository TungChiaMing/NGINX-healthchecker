FROM python:3.12-alpine

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /opt

# main.py uses only the standard library: nothing to install.
# build context is ./dbsrv -> /opt/dbsrv (run as: python3 -m dbsrv.main)
COPY main.py dbsrv/main.py

EXPOSE 211
