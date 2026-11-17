# Allowlisted apt/pip mirror for contained arenas (ROADMAP P2-3 / ADR-0005).
#
# A locked arena has no internet egress. Its foothold can reach ONLY this
# sidecar (an allowlisted forward proxy), which in turn permits ONLY package
# repositories. That lets an agent `apt`/`pip install` its tooling without
# granting general egress — no C2, no exfil to arbitrary hosts.
#
# Built on demand by the docker-local provider as `nidavellir/arena-mirror`.
FROM debian:bookworm-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends squid ca-certificates \
 && rm -rf /var/lib/apt/lists/*

COPY squid.conf /etc/squid/squid.conf

EXPOSE 3128

# Foreground, no daemonize; config disables caching so no swap dirs are needed.
CMD ["squid", "-N", "-f", "/etc/squid/squid.conf"]
