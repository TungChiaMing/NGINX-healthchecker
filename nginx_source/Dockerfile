FROM --platform=linux/amd64 ubuntu:22.04

ARG NGINX_VERSION=1.26.0

RUN apt-get update && apt-get dist-upgrade -y && \
    apt-get install -y \
      build-essential \
      libpcre3-dev \
      libssl-dev \
      zlib1g-dev \
      libgd-dev \
      libpcre3 \
      libssl3 \
      zlib1g \
      libgd3 \
      wget \
      ca-certificates && \
    rm -rf /var/lib/apt/lists/*

RUN addgroup --system nginx && \
    adduser --system --no-create-home --disabled-login --ingroup nginx nginx



# RUN wget http://nginx.org/download/nginx-${NGINX_VERSION}.tar.gz && \
#     tar -xzf nginx-${NGINX_VERSION}.tar.gz


WORKDIR /build/nginx

COPY nginx/ ./


RUN ./configure \
    --prefix=/var/www/html \
    --sbin-path=/usr/sbin/nginx \
    --modules-path=/etc/nginx/modules \
    --conf-path=/etc/nginx/nginx.conf \
    --error-log-path=/var/log/nginx/error.log \
    --pid-path=/etc/nginx/nginx.pid \
    --lock-path=/etc/nginx/nginx.lock \
    --user=nginx \
    --group=nginx \
    --with-debug \
    --with-threads \
    --with-file-aio \
    --with-http_ssl_module \
    --with-http_v2_module \
    --with-http_realip_module \
    --with-http_stub_status_module \
    --with-stream \
    --with-stream_ssl_module \
    --with-compat \
    --with-pcre-jit && \
    make -j$(nproc) && \
    make install && \
    sed -i '/http {/a \    include /etc/nginx/conf.d/*.conf;' /etc/nginx/nginx.conf


RUN mkdir -p /var/log/nginx && \
    ln -sf /dev/stdout /var/log/nginx/access.log && \
    ln -sf /dev/stderr /var/log/nginx/error.log

# RUN rm -rf /build

EXPOSE 80 8080 443
STOPSIGNAL SIGQUIT

# CMD ["/usr/sbin/nginx", "-g", "daemon off;"]