FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml MANIFEST.in ./
COPY smtpbench/ ./smtpbench/

RUN pip install .

ENTRYPOINT ["smtpbench"]
