ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:3.21
FROM ${BUILD_FROM}

ARG BUILD_ARCH=amd64
ARG BUILD_VERSION=2.2.2

LABEL \
    io.hass.name="Sunny Island" \
    io.hass.description="Plant app: Tesla EVTV BMS + live dashboard (Enphase + Tessie)" \
    io.hass.type="addon" \
    io.hass.version="${BUILD_VERSION}" \
    io.hass.arch="${BUILD_ARCH}" \
    org.opencontainers.image.title="Sunny Island" \
    org.opencontainers.image.source="https://github.com/mobiletru/sunny_island" \
    org.opencontainers.image.licenses="MIT"

ENV LANG=C.UTF-8

RUN set -eux; \
    for i in 1 2 3 4 5; do \
      apk add --no-cache nginx python3 ca-certificates curl rsync && break; \
      echo "apk retry $i"; sleep $((i * 3)); \
    done

WORKDIR /opt/sunny_island

# BMS integration + plant UI + examples
COPY custom_components/tesla_evtv_bms /opt/sunny_island/custom_components/tesla_evtv_bms
COPY dashboards /opt/sunny_island/dashboards
COPY ha_config /opt/sunny_island/ha_config
COPY rootfs/www /opt/sunny_island/www
COPY rootfs/etc/nginx/nginx.conf /etc/nginx/nginx.conf
COPY scripts/render_config.py /opt/sunny_island/render_config.py
COPY scripts/install_integration.py /opt/sunny_island/install_integration.py
COPY APP_VERSION /opt/sunny_island/APP_VERSION
COPY run.sh /run.sh

ENV SI_APP_VERSION=${BUILD_VERSION}

RUN sed -i 's/\r$//' /run.sh \
    && chmod a+x /run.sh \
    && mkdir -p /run/nginx /var/lib/nginx/tmp /var/log/nginx /tmp/nginx \
    && chown -R nginx:nginx /var/lib/nginx /var/log/nginx /run/nginx /tmp/nginx \
    && python3 -m py_compile /opt/sunny_island/render_config.py \
    && python3 -m py_compile /opt/sunny_island/install_integration.py \
    && nginx -t \
    && test -f /opt/sunny_island/custom_components/tesla_evtv_bms/manifest.json

EXPOSE 8098

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8098/health || exit 1

CMD ["/run.sh"]
