import bentoml
import joblib
import numpy as np

model = joblib.load("model/linear_regression_model.joblib")

@bentoml.service
class HousePriceService:

    @bentoml.api
    def predict(
        self,
        MedInc: float,
        Latitude: float,
        Longitude: float,
        AveRooms: float,
        HouseAge: float,
    ) -> float:
        X = np.array([[
            MedInc,
            Latitude,
            Longitude,
            AveRooms,
            HouseAge,
        ]])

        prediction = model.predict(X)[0]
        return float(prediction)