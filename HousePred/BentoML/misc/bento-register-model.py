import bentoml
import joblib

model = joblib.load("model/linear_regression_model.joblib")

bentoml.sklearn.save_model(
    "house_price_model",
    model,
)