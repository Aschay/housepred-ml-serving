#!/bin/bash


python -m venv .venv
source .venv/bin/activate        # macOS / Linux
# .venv\Scripts\activate         # Windows (PowerShell / CMD)
pip install -r requirements.txt
python model_training.py

docker build -t house-price-prediction-api:v1 .

docker run -d -p 80:80 house-price-prediction-api:v1

sleep 60

curl -X POST \
  http://127.0.0.1:80/predict \
  -H "Content-Type: application/json" \
  -d '{
    "MedInc": 35,
    "Latitude": 34.05,
    "Longitude": -118.24,
    "AveRooms": 8.0,
    "HouseAge": 10.0
  }'