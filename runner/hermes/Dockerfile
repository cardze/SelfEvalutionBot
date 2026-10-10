# Sandbox image for Hermes runner runs (design H5 of add-hermes-agent-backend).
# Built by `runner/setup.sh hermes-sandbox` as seb-runner-sandbox:latest. Python for the bot's tests,
# Node for the OpenSpec CLI, git for commits on the run branch. Nothing secret is baked in.
FROM nikolaik/python-nodejs:python3.12-nodejs22-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && npm install -g @fission-ai/openspec@1.14.1 \
 && npm cache clean --force

WORKDIR /workspace
