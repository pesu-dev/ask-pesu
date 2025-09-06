FROM python:3.12-slim-bookworm

# Copy the app and config files
COPY app /app
COPY conf /conf
COPY requirements.txt /requirements.txt

# Copy .env if it exists
COPY .env* /.env

# Install dependencies
RUN pip install -r requirements.txt

CMD ["python", "-m", "app.app"]
