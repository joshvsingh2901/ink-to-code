FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TMPDIR=/work

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        clang \
        libclang-rt-dev \
        g++ \
        libc6-dev \
        libstdc++-14-dev \
        python3 \
        valgrind \
        util-linux \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin runner

RUN mkdir -p /work && chown 10001:10001 /work && chmod 0755 /work

COPY runner.py /opt/inktocode/runner.py
RUN chmod 0555 /opt/inktocode/runner.py

COPY read_result.py /opt/inktocode/read_result.py
RUN chmod 0555 /opt/inktocode/read_result.py

USER runner
WORKDIR /work
ENTRYPOINT ["python3", "/opt/inktocode/runner.py"]
