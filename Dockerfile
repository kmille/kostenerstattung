FROM python:3.14-alpine3.23 AS builder
RUN apk add git gcc && \
    pip install poetry
COPY . /app
WORKDIR /app
RUN poetry build --format=wheel


FROM python:3.14-alpine3.23

LABEL org.opencontainers.image.source=https://github.com/kmille/kostenerstattung
LABEL org.opencontainers.image.description="Webbasiertes Tool für Kosteneinreichung, Kostenerstattung, Kommunikation und Buchhaltung in Vereinen"
LABEL org.opencontainers.image.licenses=MIT

ENV PYTHONUNBUFFERED=TRUE
ENV TZ=Europe/Berlin

RUN adduser -u 1000 -D erstattung

COPY --from=builder /app/dist/kostenerstattung*.whl .
RUN apk add git gcc libmagic tzdata && \
    pip install kostenerstattung*.whl && \
    rm kostenerstattung*.whl

USER erstattung
VOLUME /data
EXPOSE 5000
CMD /bin/sh -c "/usr/local/bin/kostenerstattung --run-backend"
