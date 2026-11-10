# Two real Nginx processes (legacy + new) and a tiny control API in one
# container, so it fits a single free web service.
#
# Python is copied from the official image instead of installed with apk, so
# the build only needs Docker Hub. control.py uses the standard library only.
FROM python:3.13-alpine AS python

FROM nginx:stable-alpine

COPY --from=python /usr/local/bin/python3.13 /usr/local/bin/python3
COPY --from=python /usr/local/lib/libpython3.13.so.1.0 /usr/local/lib/
COPY --from=python /usr/local/lib/python3.13 /usr/local/lib/python3.13

WORKDIR /app
COPY control.py legacy.conf.tmpl new.conf /app/

ENV PORT=10000 PYTHONUNBUFFERED=1
EXPOSE 10000

ENTRYPOINT []
CMD ["python3", "/app/control.py"]
