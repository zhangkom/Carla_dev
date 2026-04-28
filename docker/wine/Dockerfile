FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV WINEARCH=win64
ENV WINEPREFIX=/wineprefix
ENV WINEDEBUG=-all
ENV DISPLAY=:99
ENV PYTHONUNBUFFERED=1
ENV WINE_PYTHON_EXE=/opt/winpython/python.exe

ARG WINPY_URL=https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip

RUN dpkg --add-architecture i386 \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        cabextract \
        curl \
        procps \
        python3 \
        python3-pip \
        unzip \
        wine32 \
        wine64 \
        winbind \
        xvfb \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m pip install --no-cache-dir \
        fastapi \
        python-multipart \
        uvicorn

RUN mkdir -p /opt/winpython \
    && curl -L "$WINPY_URL" -o /tmp/winpython.zip \
    && unzip /tmp/winpython.zip -d /opt/winpython \
    && rm /tmp/winpython.zip

COPY docker/wine/wine-python /usr/local/bin/wine-python
COPY docker/wine/entrypoint.sh /usr/local/bin/carla-wine-entrypoint
RUN chmod +x /usr/local/bin/wine-python /usr/local/bin/carla-wine-entrypoint

WORKDIR /app

EXPOSE 8000

ENTRYPOINT ["/usr/local/bin/carla-wine-entrypoint"]
CMD ["python3", "-m", "uvicorn", "music_service.main:app", "--host", "0.0.0.0", "--port", "8000"]
