# Sandbox image for the Action Agent's code execution (services/sandbox.py).
# Pre-installs the libraries the agent is allowed to use so nothing gets
# pip-installed at run time (slow, and would need network access inside
# a container we deliberately run with --network none).
#
# Build once:
#   cd backend
#   docker build -t rag-agent-sandbox -f sandbox.Dockerfile .
#
# Then just start the backend normally — services/sandbox.py detects the
# image automatically (via `docker image inspect`) and uses it for every
# Action Agent run. No Docker? No problem: the agent falls back to the
# subprocess sandbox automatically, no config needed either way.
FROM python:3.11-slim

RUN pip install --no-cache-dir pandas numpy matplotlib

WORKDIR /sandbox
