FROM python:3.9-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY polybot .
EXPOSE 8443

CMD ["python", "app.py"]
