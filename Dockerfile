FROM python:3.10-slim

WORKDIR /app

# Kopiowanie wersji wygenerowanej przez GitHub Actions
COPY version.txt /app/version.txt

# Kopiowanie plików konfiguracyjnych i zależności
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip pip install --no-cache-dir -r requirements.txt

# Kopiowanie reszty kodu
COPY . .

# Tworzenie katalogów na dane i logi
RUN mkdir -p logs data

# Uruchomienie aplikacji
CMD ["python", "main.py"]