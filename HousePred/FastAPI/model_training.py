from sklearn.datasets import fetch_california_housing
from sklearn.model_selection import train_test_split
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_squared_error 
import joblib
import os

# Load the dataset
data = fetch_california_housing(as_frame=True)

df = data["data"]
target = data["target"]

selected_features = [
    "MedInc",
    "Latitude",
    "Longitude",
    "AveRooms",
    "HouseAge"
]
X = df[selected_features]
y = target

# Train-test split
X_train, X_test, y_train, y_test = train_test_split(
    X,
    y,
    test_size=0.2,
    random_state=42
)

# Train the Linear Regression model
model = LinearRegression()
model.fit(X_train, y_train)

# Evaluate on the test set
predictions = model.predict(X_test)
print("MSE:", mean_squared_error(y_test, predictions))
rmse = mean_squared_error(y_test, predictions) ** 0.5
print("RMSE:", rmse)

# Create model directory
os.makedirs("model", exist_ok=True)

# Save the trained model
joblib.dump(model, "model/linear_regression_model.joblib")

print("Model trained and saved successfully.")