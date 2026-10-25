# syntax=docker/dockerfile:1
FROM python:3.12-slim AS build
WORKDIR /src
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir --upgrade pip build \
 && python -m build --wheel --outdir /dist

FROM python:3.12-slim
LABEL org.opencontainers.image.title="trapbridge" \
      org.opencontainers.image.description="SNMP trap to Jira Service Management bridge" \
      org.opencontainers.image.source="https://github.com/ebrahimsidat/snmp-trap-jira-bridge" \
      org.opencontainers.image.licenses="MIT"
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY --from=build /dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm -f /tmp/*.whl \
 && useradd --system --uid 10001 --home-dir /var/lib/trapbridge --create-home trapbridge
USER 10001
WORKDIR /var/lib/trapbridge
EXPOSE 1162/udp
ENTRYPOINT ["trapbridge"]
CMD ["--config", "/etc/trapbridge/config.yaml"]
