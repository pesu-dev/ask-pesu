FROM python:3.12-slim-bookworm

COPY app /app
COPY conf /conf
COPY .env /.env
COPY requirements.txt /requirements.txt
RUN pip install -r requirements.txt

CMD ["python", "-m", "app.app"]
