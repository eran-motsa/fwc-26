# Optional containerised UI. Native uv + launchd is recommended (see README);
# this is here only if you later want a self-contained stack.
FROM python:3.14-slim

WORKDIR /app
COPY pyproject.toml ./
RUN pip install --no-cache-dir \
    httpx numpy scipy fastapi "uvicorn[standard]" jinja2 python-multipart python-dotenv

COPY . .
EXPOSE 8000
CMD ["uvicorn", "ui.app:app", "--host", "0.0.0.0", "--port", "8000"]
