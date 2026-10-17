FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN python manage.py makemigrations api
RUN python manage.py migrate
RUN python manage.py seed_demo
EXPOSE 8000
CMD ["gunicorn","drakshi.wsgi:application","--bind","0.0.0.0:8000","--workers","3"]
