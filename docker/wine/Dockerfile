# /**
# * File name: Dockerfile
# * Brief: MGSC DAW Docker/Wine 运行环境文件
# * Function:
# *     构建和启动云端 DAW 渲染服务所需的 Wine 容器运行环境
# * Author: 咪咕数创工程架构组
# *     MGSC AI Software Architecture group
# * Version: V2.5.10
# * Date: 2026/04/30
# */

ARG BASE_IMAGE=mcr.microsoft.com/devcontainers/base:ubuntu-22.04
FROM ${BASE_IMAGE}

ENV DEBIAN_FRONTEND=noninteractive
ENV WINEARCH=win64
ENV WINEPREFIX=/wineprefix
ENV WINEDEBUG=-all
ENV DISPLAY=:99
ENV PYTHONUNBUFFERED=1
ENV WINE_PYTHON_EXE=/opt/winpython/python.exe

ARG INSTALL_RUNTIME_DEPS=true
ARG INSTALL_VNC_DEPS=true
ARG INSTALL_BRIDGE_BUILD_DEPS=true
ARG BUILD_CARLA_WIN32_BRIDGE=true
ARG BUILD_CARLA_WIN64_BRIDGE=false
ARG APT_MIRROR=
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ARG WINE_STAGING_DEV_VERSION=9.21~jammy-1
ARG INSTALL_WINPYTHON=false
ARG WINPY_URL=https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip

RUN if [ -n "$APT_MIRROR" ] && [ -f /etc/apt/sources.list ]; then \
        sed -i \
            -e "s|http://archive.ubuntu.com/ubuntu/|$APT_MIRROR/|g" \
            -e "s|http://security.ubuntu.com/ubuntu/|$APT_MIRROR/|g" \
            /etc/apt/sources.list; \
    fi; \
    if [ -n "$APT_MIRROR" ] && [ -f /etc/apt/sources.list.d/ubuntu.sources ]; then \
        sed -i \
            -e "s|http://archive.ubuntu.com/ubuntu|$APT_MIRROR|g" \
            -e "s|http://security.ubuntu.com/ubuntu|$APT_MIRROR|g" \
            /etc/apt/sources.list.d/ubuntu.sources; \
    fi

RUN if [ "$INSTALL_RUNTIME_DEPS" = "true" ]; then \
        dpkg --add-architecture i386 \
        && apt-get update \
        && apt-get install -y --no-install-recommends \
            ca-certificates \
            cabextract \
            curl \
            ffmpeg \
            procps \
            python3 \
            python3-pip \
            unzip \
            wine32 \
            wine64 \
            winbind \
            xvfb \
        && rm -rf /var/lib/apt/lists/*; \
    else \
        echo "Skipping apt runtime dependencies because INSTALL_RUNTIME_DEPS=false"; \
    fi

RUN if [ "$INSTALL_VNC_DEPS" = "true" ]; then \
        apt-get update \
        && apt-get install -y --no-install-recommends \
            fluxbox \
            imagemagick \
            x11-apps \
            x11vnc \
            xdotool \
            xterm \
        && rm -rf /var/lib/apt/lists/*; \
    else \
        echo "Skipping VNC desktop dependencies because INSTALL_VNC_DEPS=false"; \
    fi

RUN if [ "$INSTALL_BRIDGE_BUILD_DEPS" = "true" ] && [ "$BUILD_CARLA_WIN64_BRIDGE" = "true" ]; then \
        dpkg --add-architecture i386 \
        && apt-get update \
        && apt-get install -y --no-install-recommends \
            gcc-mingw-w64-x86-64 \
            g++-mingw-w64-x86-64 \
            wine-staging-dev="$WINE_STAGING_DEV_VERSION" \
        && rm -rf /var/lib/apt/lists/*; \
    else \
        echo "Skipping win64 bridge build dependencies"; \
    fi

RUN if [ "$BUILD_CARLA_WIN64_BRIDGE" = "true" ] && [ -d /opt/carla-service ]; then \
        cd /opt/carla-service \
        && make USING_JUCE=false DISABLE_LV2=true win64 CC=x86_64-w64-mingw32-gcc CXX=x86_64-w64-mingw32-g++ \
        && make USING_JUCE=false DISABLE_LV2=true wine64; \
    else \
        echo "Skipping Carla win64 Wine bridge build"; \
    fi

RUN if [ "$INSTALL_BRIDGE_BUILD_DEPS" = "true" ] && [ "$BUILD_CARLA_WIN32_BRIDGE" = "true" ]; then \
        dpkg --add-architecture i386 \
        && apt-get update \
        && apt-get install -y --no-install-recommends \
            gcc-mingw-w64-i686 \
            g++-mingw-w64-i686 \
            g++-multilib \
            libstdc++-11-dev:i386 \
            wine-staging-dev:i386="$WINE_STAGING_DEV_VERSION" \
        && rm -rf /var/lib/apt/lists/*; \
    else \
        echo "Skipping win32 bridge build dependencies"; \
    fi

RUN if [ "$BUILD_CARLA_WIN32_BRIDGE" = "true" ] && [ -d /opt/carla-service ]; then \
        cd /opt/carla-service \
        && make USING_JUCE=false DISABLE_LV2=true win32 CC=i686-w64-mingw32-gcc CXX=i686-w64-mingw32-g++ \
        && make USING_JUCE=false DISABLE_LV2=true wine32; \
    else \
        echo "Skipping Carla win32 Wine bridge build"; \
    fi

RUN python3 -c "import importlib.util,sys; missing=[m for m in ('fastapi','uvicorn','multipart') if importlib.util.find_spec(m) is None]; print('Missing Python modules: '+', '.join(missing) if missing else 'Python modules already installed'); sys.exit(1 if missing else 0)" \
    || if [ -n "$PIP_INDEX_URL" ]; then \
        python3 -m pip install --no-cache-dir -i "$PIP_INDEX_URL" fastapi python-multipart uvicorn; \
    else \
        python3 -m pip install --no-cache-dir fastapi python-multipart uvicorn; \
    fi

RUN if [ "$INSTALL_WINPYTHON" = "true" ]; then \
        mkdir -p /opt/winpython \
        && curl -L "$WINPY_URL" -o /tmp/winpython.zip \
        && unzip /tmp/winpython.zip -d /opt/winpython \
        && rm /tmp/winpython.zip; \
    else \
        echo "Skipping Windows embeddable Python because native_bridge uses Linux Python"; \
    fi

COPY docker/wine/wine-python /usr/local/bin/wine-python
COPY docker/wine/entrypoint.sh /usr/local/bin/carla-wine-entrypoint
RUN chmod +x /usr/local/bin/wine-python /usr/local/bin/carla-wine-entrypoint

WORKDIR /app

EXPOSE 8000

ENTRYPOINT ["/usr/local/bin/carla-wine-entrypoint"]
CMD ["python3", "-m", "uvicorn", "music_service.main:app", "--host", "0.0.0.0", "--port", "8000"]
