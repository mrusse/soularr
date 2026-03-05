FROM python:3.11

WORKDIR /app

COPY requirements.txt soularr.py run.sh .
COPY webui/ webui/
COPY resources/ resources/

RUN apt-get update \
    && apt-get install -y tini \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir -r requirements.txt \
    && sed -i 's/\r$//' run.sh \
    && chmod +x run.sh

ENV PYTHONUNBUFFERED=1
ENV IN_DOCKER=Yes

EXPOSE 8265

ENTRYPOINT ["tini", "-g", "--"]
CMD ["/app/run.sh"]
