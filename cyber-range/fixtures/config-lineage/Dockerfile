ARG PYTHON_IMAGE=python:3.11.14-alpine
FROM ${PYTHON_IMAGE}
WORKDIR /app
COPY cyber-range/fixtures/nv06-authz/app.py /app/base_app.py
COPY cyber-range/fixtures/nv06-authz/library-v1.json /app/library-v1.json
COPY cyber-range/fixtures/config-lineage/app.py /app/app.py
ENV PYTHONDONTWRITEBYTECODE=1
USER 65534:65534
EXPOSE 8080
ENTRYPOINT ["python", "/app/app.py"]
