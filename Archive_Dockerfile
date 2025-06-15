FROM python:3.9-slim-buster

WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code.  Consider a .dockerignore file to exclude
# unwanted files (like .git)
COPY . .

# Cloud Run sets the PORT environment variable.  We set a default here
# For local testing.  This will be overridden by Cloud Run.
ENV PORT 8080

# Documentation on what port this container will listen on.
EXPOSE 8080

# Command to run the Flask app using Gunicorn
# 'app:app' means 'from app.py, run the Flask app instance named app'
# '$PORT' ensures gunicorn listens on the port provided by Cloud Run

#Cloud Run and most Docker-based platforms ignore Procfile by default. They only use the Dockerfile’s CMD or ENTRYPOINT.
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--threads", "8", "--log-level", "debug", "app:app"]
