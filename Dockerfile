# Use an official lightweight Python runtime
FROM python:3.13.3-alpine3.21

# Prevent Python from writing pyc files and buffer stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Set working directory
WORKDIR /app

# Create a non-root user with explicit UID/GID 1000
RUN addgroup -g 1000 -S appgroup && adduser -u 1000 -S appuser -G appgroup

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt --upgrade

# Copy application files with proper non-root ownership in a single step
COPY --chown=appuser:appgroup . .

# Switch to non-root user
USER appuser

# Healthcheck to verify the python process can execute
HEALTHCHECK --interval=60s --timeout=10s --retries=3 \
  CMD python -c "import sys; sys.exit(0)" || exit 1

# Run application
CMD ["python", "main.py"]
