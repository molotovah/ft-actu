FROM mcr.microsoft.com/playwright/python:v1.64.0-noble
RUN pip install --no-cache-dir playwright==1.64.0 webauthn==3.0.1 segno==1.6.6
ENV TZ=Europe/Paris PYTHONUNBUFFERED=1
WORKDIR /app
COPY app.py web.py auth.py ./
COPY static static
CMD ["python", "web.py"]
