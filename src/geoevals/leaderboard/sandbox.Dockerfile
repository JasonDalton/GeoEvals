# Sandbox for the python track of the Claude leaderboard. requirements.txt is exported from the
# project's uv.lock (runtime dependencies plus the network extra), with hashes.
FROM python:3.12-slim
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --require-hashes -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt
USER 65534:65534
