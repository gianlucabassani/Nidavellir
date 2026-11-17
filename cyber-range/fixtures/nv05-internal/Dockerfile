FROM python:3.11.14-alpine3.22
WORKDIR /app
COPY app.py /app/app.py
USER 65534:65534
ENTRYPOINT ["python3", "-E", "/app/app.py"]
