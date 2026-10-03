# FastAPI + Docker + Kubernetes + HPA

This guide deploys the HousePred model as a conventional Python application:

```text
FastAPI
   ↓
Docker
   ↓
Kubernetes Deployment
   ↓
Kubernetes Service
   ↓
HPA
```

This is the baseline deployment used to compare conventional application serving with BentoML and KServe.

## 1. Prerequisites

Required:

* Docker Desktop
* Docker Desktop Kubernetes enabled
* `kubectl`
* Python 3.12
* A working HousePred project

Verify:

```bash
docker --version
kubectl version --client
python --version
```

## 2. Project Structure

The relevant files are:

```text
HousePred/
├── app/
│   └── main.py
├── model/
│   └── linear_regression_model.joblib
├── requirements.txt
├── Dockerfile
└── housepred.yaml
```

The model is the same California housing regression model used by the other serving implementations.

## 3. FastAPI Application

The application:

* Loads the model during application startup.
* Exposes `/predict`.
* Exposes `/healthz` for liveness.
* Exposes `/ready` for readiness.
* Returns HTTP 503 from `/ready` until the model is loaded.

The important distinction is that model loading is handled by the application itself.

## 4. Build the Docker Image

The application uses a multi-stage Docker build.

```dockerfile
FROM python:3.12.4-slim AS builder
WORKDIR /app
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM python:3.12.4-slim
RUN useradd --create-home --uid 1000 appuser
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY app/ ./app/
COPY model/ ./model/
USER appuser
EXPOSE 80
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "80"]
```

Build:

```bash
docker build -t housepred:1.0 .
```

## 5. Test the Container Locally

Run:

```bash
docker run --rm -p 8080:80 housepred:1.0
```

Health:

```bash
curl http://localhost:8080/healthz
```

Readiness:

```bash
curl http://localhost:8080/ready
```

Prediction:

```bash
curl -X POST http://localhost:8080/predict \
  -H "Content-Type: application/json" \
  -d "{\"MedInc\":8.3252,\"Latitude\":37.88,\"Longitude\":-122.23,\"AveRooms\":6.9841,\"HouseAge\":41.0}"
```

## 6. Kubernetes Deployment

The Kubernetes Deployment runs the container as a Pod.

The deployment includes:

* Resource requests
* Resource limits
* Liveness probe
* Readiness probe
* Multiple replicas

The readiness probe uses:

```text
/ready
```

The liveness probe uses:

```text
/healthz
```

Apply the manifest:

```bash
kubectl apply -f housepred.yaml
```

Check:

```bash
kubectl get deployment
kubectl get pods
```

## 7. Kubernetes Service

The Service provides a stable network endpoint in front of the Pods.

Check:

```bash
kubectl get service
```

The Service selects the Pods created by the Deployment.

The request path is:

```text
Client
  ↓
Service
  ↓
Pod
  ↓
FastAPI
  ↓
Model
```

## 8. Test the Kubernetes Deployment

For local Docker Desktop Kubernetes, expose the application through the configured Service.

The project used the NodePort endpoint:

```text
http://localhost:30080
```

Prediction:

```bash
curl -X POST http://localhost:30080/predict \
  -H "Content-Type: application/json" \
  -d "{\"MedInc\":8.3252,\"Latitude\":37.88,\"Longitude\":-122.23,\"AveRooms\":6.9841,\"HouseAge\":41.0}"
```

## 9. HPA

The Horizontal Pod Autoscaler scales the Deployment according to resource utilization.

The important detail is that CPU utilization is evaluated relative to the Pods' CPU requests.

Conceptually:

```text
CPU usage
    ↓
compare against CPU request
    ↓
HPA calculates desired replicas
    ↓
Deployment changes Pod count
```

The HPA was configured with a CPU utilization target.

Check:

```bash
kubectl get hpa
```

Detailed information:

```bash
kubectl describe hpa
```

## 10. Metrics Server

HPA requires a metrics source.

For this local Kubernetes environment, Metrics Server was installed while validating HPA behavior.

It can be checked with:

```bash
kubectl top pods
kubectl top nodes
```

The Metrics Server installation itself is infrastructure supporting HPA; it is not part of the FastAPI application.

## 11. Scaling Model

This deployment uses resource-based autoscaling:

```text
                 Kubernetes
                     │
                 Deployment
                     │
                   HPA
                     │
          CPU utilization target
                     │
             ┌───────┴───────┐
             ↓               ↓
          fewer Pods      more Pods
```

Unlike the KServe + Knative deployment, this architecture does not provide HTTP request-driven scale-to-zero.

## 12. Final Architecture

```text
Client
  │
  ▼
Kubernetes Service
  │
  ▼
FastAPI Pods
  │
  ▼
HousePred model

             ▲
             │
            HPA
             │
       CPU utilization
```

This is the baseline architecture for the project.

It demonstrates conventional application serving and Kubernetes autoscaling without introducing an ML-specific serving platform.
