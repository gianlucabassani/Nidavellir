FROM python:3.11.14-alpine3.22

RUN addgroup -g 65532 nidavellir \
    && adduser -D -H -u 65532 -G nidavellir nidavellir \
    && mkdir -p /opt/nidavellir /workspace /run/nidavellir \
    && chown -R 65532:65532 /workspace /run/nidavellir
COPY runner.py relay.py proxy.py tcp_relay.py /opt/nidavellir/
COPY client.py /usr/local/lib/python3.11/site-packages/nidavellir.py
USER 65532:65532
WORKDIR /workspace
ENTRYPOINT ["python3", "-E", "/opt/nidavellir/runner.py"]
