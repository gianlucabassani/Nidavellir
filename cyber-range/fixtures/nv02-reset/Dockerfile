ARG PYTHON_IMAGE=python:3.11.14-alpine
FROM ${PYTHON_IMAGE}
WORKDIR /app
COPY app.py /app/app.py
USER 65534:65534
EXPOSE 8080
ENTRYPOINT ["python", "/app/app.py"]
