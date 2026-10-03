from fastapi import FastAPI
from pydantic import BaseModel
import joblib
import numpy as np


model = joblib.load("model/linear_regression_model.joblib")

app = FastAPI(
    title="house-price-predictor"
)


class InputData(BaseModel):
    MedInc: float
    Latitude: float
    Longitude: float
    AveRooms: float
    HouseAge: float


class PredictionResponse(BaseModel):
    predicted_house_price: float


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/ready")
def ready():
    return {"status": "ready"}


@app.post("/predict", response_model=PredictionResponse)
def predict(data: InputData):
    X = np.array([[
        data.MedInc,
        data.Latitude,
        data.Longitude,
        data.AveRooms,
        data.HouseAge
    ]])

    prediction = model.predict(X)[0]

    return {
        "predicted_house_price": float(prediction)
    }