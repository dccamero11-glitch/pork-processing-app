FROM python:3.12-slim
WORKDIR /app
COPY requirements-production.txt .
RUN pip install --no-cache-dir -r requirements-production.txt
COPY . .
ENV APP_ENV=production HOST=0.0.0.0 PORT=8080
EXPOSE 8080
CMD ["python", "app.py"]
