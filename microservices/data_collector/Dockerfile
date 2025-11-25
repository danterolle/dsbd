FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ./app .

# Compila il file proto in codice Python
RUN python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. service.proto

EXPOSE 5000

CMD ["python", "app.py"]