FROM python:3.11-slim AS runtime

RUN addgroup --system contoso && adduser --system --ingroup contoso contoso

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY reconcile.py ./
COPY sample_feed.csv ./

RUN chown -R contoso:contoso /app
USER contoso

CMD ["python", "reconcile.py"]
