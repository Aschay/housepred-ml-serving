# FastAPI + Docker + Kubernetes + HPA — Setup Guide

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

### Requirements

* Python 3.12
* A container runtime
* A Kubernetes cluster
* `kubectl`
* A working HousePred project

### Local Environment Used

* Docker Desktop
* Docker Desktop Kubernetes

Verify:

```bash
docker --version
kubectl version --client
python --version
```

## 2. Project Structure

The relevant FastAPI files are:

```text
FastAPI/
├── app/
│   └── main.py
├── model/
│   └── linear_regression_model.joblib
├── requirements.txt
├── Dockerfile
└── k8s/
    ├── housepred.yaml
    └── housepred-hpa.yaml
```

The project also contains the model-training script and a helper script for building and testing the container, but they are not required for the Kubernetes deployment itself.

The model is the same California Housing regression model used by the other serving implementations.

## 3. FastAPI Application

The application:

* Loads the model when the application module is imported.
* Exposes `/predict`.
* Exposes `/healthz` for liveness.
* Exposes `/ready` for readiness.

The important distinction is that **model loading and the inference API are implemented directly by the application**.

The application loads:

```python
model = joblib.load("model/linear_regression_model.joblib")
```

and the `/predict` endpoint converts the request into a NumPy array before calling the scikit-learn model.

The `/ready` endpoint currently returns a successful response once the application is running; it does not implement a separate model-loading state that returns HTTP 503.

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

The multi-stage build keeps the runtime image separate from the builder stage and runs the application as the non-root `appuser`.

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
  -d '{"MedInc":8.3252,"Latitude":37.88,"Longitude":-122.23,"AveRooms":6.9841,"HouseAge":41.0}'
```

## 6. Kubernetes Deployment

The Kubernetes Deployment runs the container as a Pod.

The Deployment specifies:

* one initial replica
* CPU and memory requests
* CPU and memory limits
* a liveness probe
* a readiness probe

The initial replica count is:

```yaml
replicas: 1
```

The HPA can later increase the number of replicas when the configured scaling conditions are met.

The readiness probe uses:

```text
/ready
```

The liveness probe uses:

```text
/healthz
```

Apply the Deployment and Service:

```bash
kubectl apply -f k8s/housepred.yaml
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

The Service selects the Pods created by the Deployment using:

```text
app: housepred
```

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

The Service is configured as a `NodePort` and exposes port `30080` on the Kubernetes node.
The NodePort is used here only for local testing; in production, the service would typically be exposed through the environment's normal ingress, Gateway API, or load-balancing layer.

## 8. Test the Kubernetes Deployment

For local Docker Desktop Kubernetes, the project exposes the application through the configured NodePort:

```text
http://localhost:30080
```

Prediction:

```bash
curl -X POST http://localhost:30080/predict \
  -H "Content-Type: application/json" \
  -d '{"MedInc":8.3252,"Latitude":37.88,"Longitude":-122.23,"AveRooms":6.9841,"HouseAge":41.0}'
```

The request is routed through the Kubernetes Service to one of the available HousePred Pods.

## 9. HPA

The Horizontal Pod Autoscaler scales the `housepred` Deployment according to CPU utilization.

The important detail is that CPU utilization is evaluated relative to the Pods' CPU **requests**.

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

The project configures:

```text
Minimum replicas: 1
Maximum replicas: 5
CPU target: 70%
```

The HPA targets:

```text
Deployment/housepred
```

Check:

```bash
kubectl get hpa
```

Detailed information:

```bash
kubectl describe hpa
```

The HPA itself does not execute the inference workload. It changes the desired replica count of the Deployment.

## 10. Metrics Server

HPA requires a metrics source for CPU-based scaling.

For this local Kubernetes environment, Metrics Server was installed while validating HPA behavior.

It can be checked with:

```bash
kubectl top pods
kubectl top nodes
```

The Metrics Server provides the resource metrics consumed by the HPA. It is infrastructure supporting Kubernetes autoscaling rather than part of the FastAPI application.

## 11. Scaling Model

This deployment uses **resource-based autoscaling**:

```text
                 Kubernetes
                     │
                 Deployment
                     │
                    HPA
                     │
             CPU utilization target
                     │
            ┌────────┴────────┐
            ↓                 ↓
       fewer Pods         more Pods
```

The deployment starts with one Pod and can scale between one and five replicas according to the HPA configuration.

Unlike the KServe + Knative deployment, this architecture does not provide HTTP request-driven scale-to-zero.

## 12. Final Architecture

```text
Client
  │
  ▼
Kubernetes Service
  │
  ▼
FastAPI Pod(s)
  │
  ▼
HousePred model

      ▲
      │
     HPA
      │
CPU utilization
```

The HPA operates on the Deployment rather than directly on the FastAPI application:

```text
                    Deployment
                        │
                  ┌─────┴─────┐
                  │           │
               Pod 1        Pod 2 ...
                  │
               FastAPI
                  │
                Model

                    ▲
                    │
                   HPA
```

This is the baseline architecture for the project.

It demonstrates conventional application serving and Kubernetes resource-based autoscaling without introducing an ML-specific serving platform.
