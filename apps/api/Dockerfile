FROM python:3.12-slim@sha256:b18b261e1b4974b4f321451ad5251ded85abb22c2b8b262da527dda1d031ab30
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_LINK_MODE=copy
WORKDIR /app/apps/api
RUN pip install --no-cache-dir uv==0.13.7
COPY apps/api/pyproject.toml apps/api/uv.lock ./
RUN uv sync --frozen --no-dev
ENV PATH="/app/apps/api/.venv/bin:$PATH"
COPY apps/api ./
COPY shared /app/shared
COPY apps/web/public/examples /app/apps/web/public/examples
COPY apps/web/public/templates /app/apps/web/public/templates
RUN useradd --uid 10001 --create-home atoms && mkdir -p /var/lib/atoms && chown atoms:atoms /var/lib/atoms
USER atoms
EXPOSE 8000
CMD ["uvicorn","atoms.main:app","--host","0.0.0.0","--port","8000","--no-access-log"]
