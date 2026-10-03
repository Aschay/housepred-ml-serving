# BentoML

This guide deploys the HousePred model using BentoML, then runs the resulting container on Kubernetes with a Service and HPA.

## 1. Prerequisites

* Python 3.12
* Docker
* Docker Desktop Kubernetes
* `kubectl`
* BentoML 1.4.39

Install BentoML:

```bash
python -m pip install bentoml
```

Verify:

```bash
bentoml --version
```

---

## 2. BentoML Service

Create `service.py`:

```python
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
```

BentoML provides the serving infrastructure around this API, including API documentation, health endpoints, readiness/liveness endpoints, metrics, and logging.

The inference endpoint is:

```text
POST /predict
```

BentoML also exposes:

```text
GET /healthz
GET /livez
GET /readyz
GET /metrics
```

These are BentoML's built-in infrastructure endpoints; they do not need to be implemented in `service.py`.

---

## 3. Test the Service Locally

Start BentoML:

```bash
bentoml serve service:HousePriceService
```

The service runs on:

```text
http://localhost:3000
```

Test prediction:

```bash
curl -X POST http://localhost:3000/predict \
  -H "Content-Type: application/json" \
  -d '{"MedInc":8.3252,"Latitude":37.88,"Longitude":-122.23,"AveRooms":6.9841,"HouseAge":41.0}'
```

Expected result:

```text
4.080089668998603
```

BentoML also provides Swagger/OpenAPI documentation at:

```text
http://localhost:3000
```

---

## 4. Bento Configuration

Create `bentofile.yaml`:

```yaml
service: "service:HousePriceService"

include:
  - "service.py"
  - "model/linear_regression_model.joblib"

python:
  packages:
    - bentoml==1.4.39
    - scikit-learn==1.9.0
    - joblib==1.5.3
    - numpy==2.4.2
    - pandas==3.0.6
    - scipy==1.18.1
    - threadpoolctl==3.7.0
```

The `include` section packages both the service code and the trained model into the Bento.

---

## 5. Build the Bento

Run:

```bash
bentoml build
```

The resulting Bento is identified by its name and version, for example:

```text
house_price_service:k4p3o6v6pgcsjabl
```

List available Bentos:

```bash
bentoml list
```

---

## 6. BentoML Model Store

The trained model can also be registered in BentoML's Model Store:

```python
import bentoml
import joblib

model = joblib.load("model/linear_regression_model.joblib")

bentoml.sklearn.save_model(
    "house_price_model",
    model,
)
```

List registered models:

```bash
bentoml models list
```

The Kubernetes container used in this project loads the `.joblib` file directly from the Bento rather than loading the model from the BentoML Model Store.

---

## 7. Containerize the Bento

Create the Docker image from the Bento:

```bash
bentoml containerize house_price_service:k4p3o6v6pgcsjabl
```

BentoML produces an image tagged:

```text
house_price_service:k4p3o6v6pgcsjabl
```

Run it locally:

```bash
docker run --rm -p 3000:3000 house_price_service:k4p3o6v6pgcsjabl
```

Test:

```bash
curl -X POST http://localhost:3000/predict \
  -H "Content-Type: application/json" \
  -d '{"MedInc":8.3252,"Latitude":37.88,"Longitude":-122.23,"AveRooms":6.9841,"HouseAge":41.0}'
```

---

## 8. Built-in Metrics

BentoML exposes Prometheus-compatible metrics at:

```text
GET /metrics
```

For example:

```bash
curl http://localhost:3000/metrics
```

The metrics include request counts, requests in progress, request duration, and request timestamps.

This gives the BentoML serving layer built-in observability without implementing application-level metrics manually.

---

## 9. Kubernetes Namespace

Create the namespace:

```bash
kubectl create namespace bentoml
```

---

## 10. Kubernetes Deployment

The BentoML container runs as a normal Kubernetes Deployment.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: housepred-bento
  namespace: bentoml
spec:
  replicas: 1
  selector:
    matchLabels:
      app: housepred-bento
  template:
    metadata:
      labels:
        app: housepred-bento
    spec:
      containers:
        - name: housepred
          image: house_price_service:k4p3o6v6pgcsjabl
          imagePullPolicy: Never
          ports:
            - containerPort: 3000

          livenessProbe:
            httpGet:
              path: /livez
              port: 3000
            initialDelaySeconds: 10
            periodSeconds: 10

          readinessProbe:
            httpGet:
              path: /readyz
              port: 3000
            initialDelaySeconds: 5
            periodSeconds: 5

          resources:
            requests:
              cpu: "100m"
              memory: "128Mi"
            limits:
              cpu: "500m"
              memory: "512Mi"
```

The probes use BentoML's built-in infrastructure endpoints:

* `/livez` → Kubernetes liveness probe
* `/readyz` → Kubernetes readiness probe

Resource requests and limits are also defined so Kubernetes can schedule the workload and the HPA can calculate CPU utilization relative to the CPU request.

Apply:

```bash
kubectl apply -f bento-deployment.yaml
```

Check:

```bash
kubectl get pods -n bentoml
```

---

## 11. Kubernetes Service

Expose the BentoML application through a NodePort:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: housepred-bento
  namespace: bentoml
spec:
  type: NodePort
  selector:
    app: housepred-bento
  ports:
    - port: 3000
      targetPort: 3000
      nodePort: 30090
```

Apply:

```bash
kubectl apply -f bento-service.yaml
```

The service is available at:

```text
http://localhost:30090
```

Test prediction:

```bash
curl -X POST http://localhost:30090/predict \
  -H "Content-Type: application/json" \
  -d '{"MedInc":8.3252,"Latitude":37.88,"Longitude":-122.23,"AveRooms":6.9841,"HouseAge":41.0}'
```

---

## 12. Kubernetes HPA

BentoML itself is not the Kubernetes autoscaler. Kubernetes HPA handles replica scaling.

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: housepred
  namespace: bentoml
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: housepred-bento
  minReplicas: 1
  maxReplicas: 5
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
```

Apply:

```bash
kubectl apply -f bento-hpa.yaml
```

Check:

```bash
kubectl get hpa -n bentoml
```

The HPA target is:

```text
70% average CPU utilization
```

CPU utilization is calculated relative to the container's CPU request:

```text
CPU utilization =
    actual CPU usage / requested CPU
```

With:

```yaml
requests:
  cpu: "100m"
```

70% corresponds to approximately:

```text
70m CPU
```

across the HPA's target calculation.

---

## 13. Metrics Server

The Kubernetes HPA requires resource metrics.

Check Metrics Server:

```bash
kubectl get pods -n kube-system | grep metrics-server
```

Verify metrics:

```bash
kubectl top pods -n bentoml
```

Example:

```text
NAME                               CPU(cores)   MEMORY(bytes)
housepred-bento-...                3m           282Mi
```

The HPA can then obtain CPU utilization from the Kubernetes Metrics API.

---

## 14. HPA Load Test

Generate continuous prediction traffic:

```bash
while true; do
  curl -s -X POST http://localhost:30090/predict \
    -H "Content-Type: application/json" \
    -d '{"MedInc":8.3252,"Latitude":37.88,"Longitude":-122.23,"AveRooms":6.9841,"HouseAge":41.0}' > /dev/null
done
```

In another terminal:

```bash
kubectl get hpa -n bentoml
```

The HPA can be observed receiving CPU metrics while traffic is running.

For this project, the measured workload remained below the 70% threshold, so the Deployment correctly remained at one replica.

The important part demonstrated here is the complete metrics path:

```text
BentoML Pod
    ↓
CPU usage
    ↓
Metrics Server
    ↓
HPA
    ↓
Kubernetes Deployment replicas
```

---

## 15. BentoML vs KServe Autoscaling

BentoML and KServe solve different layers of the serving problem.

### BentoML

```text
BentoML
   ↓
Docker image
   ↓
Kubernetes Deployment
   ↓
Kubernetes Service
   ↓
HPA
```

BentoML provides the application serving layer:

* model-serving API
* request validation
* Swagger/OpenAPI
* health endpoints
* readiness/liveness endpoints
* metrics
* logging
* containerization
* Model Store

Kubernetes provides:

* scheduling
* replicas
* networking
* resource management
* HPA
* infrastructure orchestration

BentoML does not itself provide Knative-style request-driven scale-to-zero.

### KServe + Knative

```text
KServe
   ↓
InferenceService
   ↓
Knative
   ↓
Kourier
   ↓
scale-to-zero
```

KServe integrates model serving with Kubernetes-native resources and, in Knative mode, provides request-driven autoscaling and scale-to-zero.

This is a different architectural approach from putting a BentoML application inside a normal Kubernetes Deployment.

---

## 16. Final Architecture

The BentoML implementation is:

```text
HousePred Model
      │
      ▼
   BentoML
      │
      ▼
  Bento Build
      │
      ▼
 Docker Image
      │
      ▼
Kubernetes Deployment
      │
      ├── /livez
      ├── /readyz
      ├── /metrics
      └── /predict
      │
      ▼
 Kubernetes Service
      │
      ▼
 NodePort :30090
      │
      ▼
     HPA
      │
      ▼
Metrics Server
      │
      ▼
1–5 Kubernetes replicas
```

The key distinction is:

```text
FastAPI
    → build the serving application yourself

BentoML
    → standardized ML serving application + packaging

KServe
    → Kubernetes-native model-serving platform
```

BentoML therefore sits between a hand-built FastAPI application and a Kubernetes-native serving platform such as KServe.
