# Optional container build: frontend is built and served by the backend on port 8000.
FROM node:22-alpine AS web
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./
COPY data/nse_holidays.json /app/data/nse_holidays.json
COPY --from=web /app/frontend/dist /app/frontend/dist
# Inside the container the server must listen on all interfaces; docker-compose publishes
# it on 127.0.0.1 only, so it is still not exposed to your network.
ENV PT_HOST=0.0.0.0
EXPOSE 8000
CMD ["python", "run.py"]
