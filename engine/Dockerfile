FROM ubuntu:24.04 AS build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential cmake libboost-dev libssl-dev libgtest-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src
COPY . .

RUN cmake -S . -B build -DCMAKE_BUILD_TYPE=Release \
    && cmake --build build --target personal_cloud_engine --parallel

FROM ubuntu:24.04

RUN apt-get update && apt-get install -y --no-install-recommends curl libssl3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=build /src/build/personal_cloud_engine /app/personal_cloud_engine
COPY scripts/healthcheck.sh /app/scripts/healthcheck.sh
RUN chmod +x /app/scripts/healthcheck.sh

EXPOSE 9000

CMD ["/app/personal_cloud_engine"]
