FROM python:3.12-slim
WORKDIR /srv/evenspace
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY requirements-meetings.txt .
RUN pip install --no-cache-dir -r requirements-meetings.txt
COPY app ./app
COPY migrations ./migrations
COPY alembic.ini .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

