ARG PYTHON_IMAGE=python:3.11.14-alpine
FROM ${PYTHON_IMAGE}
WORKDIR /app
COPY app.py /app/app.py
COPY library-v1.json /app/library-v1.json
COPY index.html /app/index.html
COPY app.js /app/app.js
USER 65534:65534
EXPOSE 8080
ENTRYPOINT ["python", "/app/app.py"]
