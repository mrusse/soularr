FROM python:3.11

WORKDIR /app

COPY requirements.txt soularr.py argparser.py soularr_types.py utils.py main.py config.py run.sh .

RUN apt-get update \
    && apt-get install -y tini \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir -r requirements.txt \
    && sed -i 's/\r$//' run.sh \
    && chmod +x run.sh

ENV PYTHONUNBUFFERED=1
ENV IN_DOCKER=Yes

ENTRYPOINT ["tini", "-g", "--"]
CMD ["/app/run.sh"]
