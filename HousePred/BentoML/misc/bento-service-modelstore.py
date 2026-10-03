import bentoml
import numpy as np

model = bentoml.sklearn.load_model("house_price_model:henca7f6ps2dnabl")

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