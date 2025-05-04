FROM python:3.11

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1
ENV IN_DOCKER=Yes

ENTRYPOINT ["bash", "run.sh"]
