FROM python:3.10-slim

WORKDIR /app

# Kopiuj wersję wygenerowaną przez GitHub Actions
COPY version.txt /app/version.txt

# Kopiuj pliki konfiguracyjne i zależności
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Kopiuj resztę kodu
COPY . .

# Utwórz katalogi na dane i logi
RUN mkdir -p logs data

# Uruchom bota
CMD ["python", "main.py"]