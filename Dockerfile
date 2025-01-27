FROM python:3.11

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN sed -i 's/\r$//' run.sh

RUN chmod +x run.sh

ENV PYTHONUNBUFFERED=1
ENV IN_DOCKER=Yes

ENTRYPOINT ["bash", "run.sh"]