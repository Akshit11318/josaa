# Official Playwright image ships Chromium + all system deps preinstalled.
FROM mcr.microsoft.com/playwright/python:v1.48.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Browsers already exist in the base image; ensure the version matches the pinned lib.
RUN python -m playwright install chromium

COPY . .

# Default to an idle shell; real work is run via `docker compose run app <cmd>`.
CMD ["bash"]
