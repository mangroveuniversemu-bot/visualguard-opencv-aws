# VisualGuard container image.
#
#   target "http"   -> App Runner / ECS Fargate / local (port 8080)
#   target "lambda" -> AWS Lambda container image (Function URL or API Gateway)
#
# The base is pinned by digest. Where Docker Hub is rate limited, pass a
# pull-through mirror of the same digest, for example:
#   --build-arg BASE_IMAGE=mirror.gcr.io/library/python:3.12-slim@sha256:cb33f7f771ecec2ef1225cf39b159591a040391bd73e4c01f00fdfc4c47611d2
ARG BASE_IMAGE=python:3.12-slim@sha256:cb33f7f771ecec2ef1225cf39b159591a040391bd73e4c01f00fdfc4c47611d2

FROM ${BASE_IMAGE} AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    VISUALGUARD_LEDGER_PATH=/tmp/visualguard/capture-replay.sqlite3
WORKDIR /app
COPY requirements-vision.txt ./
# Optional build secret "pip_ca" supplies a TLS-intercepting proxy's CA at
# build time only; it is never written to an image layer.
RUN --mount=type=secret,id=pip_ca,required=false \
    if [ -f /run/secrets/pip_ca ]; then export PIP_CERT=/run/secrets/pip_ca; fi; \
    pip install -r requirements-vision.txt
COPY vision/ vision/
COPY service/ service/
RUN python -c "import cv2; assert cv2.__version__ == '5.0.0', cv2.__version__"

FROM base AS lambda
COPY requirements-lambda.txt ./
RUN --mount=type=secret,id=pip_ca,required=false \
    if [ -f /run/secrets/pip_ca ]; then export PIP_CERT=/run/secrets/pip_ca; fi; \
    pip install -r requirements-lambda.txt
USER 10001
ENTRYPOINT ["python", "-m", "awslambdaric"]
CMD ["service.lambda_handler.handler"]

FROM base AS http
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin visualguard
USER 10001
ENV PORT=8080
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=4)"]
CMD ["python", "-m", "service.app", "--host", "0.0.0.0", "--port", "8080"]
