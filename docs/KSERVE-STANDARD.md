# KServe Standard — Setup Guide

This guide documents the **KServe Standard deployment** implemented for HousePred.

The deployment demonstrates:

* Kubernetes-native model serving with KServe
* KServe Standard deployment mode
* Persistent model storage using a Kubernetes PVC
* A custom KServe `ClusterServingRuntime`
* sklearn model serving with `sklearnserver`
* Kubernetes-native predictor deployment

Unlike the separate **KServe + Knative + Kourier** deployment, this setup does **not** use Knative Serving, Kourier, KPA, scale-to-zero, or scale-from-zero.

The completed serving architecture is:

```text
HousePred model
      ↓
PersistentVolumeClaim
      ↓
KServe InferenceService
      ↓
KServe Controller
      ↓
Kubernetes Deployment
      ↓
Predictor Pod
      ↓
Serving Runtime
      ↓
Kubernetes Service
      ↓
Prediction
```

---

# 1. Prerequisites

## Requirements

The environment requires:

* Python 3.12
* A container runtime
* Kubernetes cluster
* `kubectl`
* Helm
* Sufficient CPU and memory for Kubernetes, KServe, cert-manager, and the model runtime
* A working HousePred project with the trained model artifact

The model used by this deployment is:

```text
model/
└── linear_regression_model.joblib
```

## Local Environment

The Standard deployment was tested using:

* Docker
* Ubuntu
* Kubernetes
* `local-path` StorageClass

Verify the environment:

```bash
kubectl version --client
kubectl get nodes
helm version
kubectl get storageclass
```

The `local-path` StorageClass is used for the model PVC.

---

# 2. Serving Infrastructure

The Standard deployment requires cert-manager and KServe.

The architecture is:

```text
KServe
  ↓
Kubernetes
  ↓
Predictor
```

## 2.1 cert-manager

KServe v0.20.0 requires cert-manager resources for the KServe installation.

Install cert-manager:

```bash
kubectl apply -f \
  https://github.com/cert-manager/cert-manager/releases/download/v1.21.2/cert-manager.yaml
```

Verify:

```bash
kubectl get pods -n cert-manager
```

Wait until the cert-manager components are running.

---

# 3. Install KServe

KServe is installed using Helm.

The deployment uses:

```text
KServe v0.20.0
Deployment Mode: Standard
```

## 3.1 Install KServe CRDs

```bash
helm install kserve-crd \
  oci://ghcr.io/kserve/charts/kserve-crd \
  --version v0.20.0 \
  --namespace kserve \
  --create-namespace
```

Verify:

```bash
kubectl get crd | grep kserve
```

## 3.2 Install KServe Resources

Install KServe in **Standard** deployment mode:

```bash
helm install kserve-resources \
  oci://ghcr.io/kserve/charts/kserve-resources \
  --version v0.20.0 \
  --namespace kserve \
  --set kserve.controller.deploymentMode=Standard \
  --wait
```

Verify:

```bash
kubectl get pods -n kserve
```

The KServe controller should be running.

---

# 4. The HousePred Serving Pipeline

The HousePred serving pipeline consists of three main components:

```text
HousePred Model
      ↓
KServe InferenceService
      ↓
Kubernetes Predictor
```

The `InferenceService` declares which model should be served.

The `ClusterServingRuntime` defines which model server should be used.

KServe then creates the Kubernetes resources required to run the predictor.

The resulting Standard serving path is:

```text
InferenceService
      ↓
KServe Controller
      ↓
Deployment
      ↓
ReplicaSet
      ↓
Predictor Pod
      ↓
sklearnserver
```

---

# 4.1. Prepare Model Storage

The trained HousePred model is stored locally and copied into a Kubernetes PersistentVolumeClaim.

The model artifact is:

```text
linear_regression_model.joblib
```

The storage architecture is:

```text
local-path StorageClass
      ↓
PersistentVolumeClaim
      ↓
/mnt/models
      ↓
linear_regression_model.joblib
```

## 4.1.1 Create the PVC

Create `pvc.yaml`:

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: kserve-model-pvc
  namespace: kserve
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 1Gi
  storageClassName: local-path
```

Apply it:

```bash
kubectl apply -f pvc.yaml
```

Check the PVC:

```bash
kubectl get pvc -n kserve
```

The PVC may initially show:

```text
Pending
```

This is expected with the `local-path` StorageClass because the volume uses `WaitForFirstConsumer`.

## 4.1.2 Create the Model Loader

Create `model-loader.yaml`:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: model-loader
  namespace: kserve
spec:
  containers:
    - name: loader
      image: busybox:1.36
      command: ["sh", "-c", "sleep 3600"]
      volumeMounts:
        - name: model
          mountPath: /mnt/models
  volumes:
    - name: model
      persistentVolumeClaim:
        claimName: kserve-model-pvc
```

Apply it:

```bash
kubectl apply -f model-loader.yaml
```

Check the PVC:

```bash
kubectl get pvc -n kserve
```

It should now become:

```text
Bound
```

## 4.1.3 Copy the Model

Copy the trained model into the mounted PVC:

```bash
kubectl cp \
  model/linear_regression_model.joblib \
  kserve/model-loader:/mnt/models/linear_regression_model.joblib
```

Verify the model:

```bash
kubectl exec -n kserve model-loader -- \
  ls -lh /mnt/models
```

The directory should contain:

```text
linear_regression_model.joblib
```

The temporary model-loader pod can now be removed:

```bash
kubectl delete pod model-loader -n kserve
```

The PVC remains available after the pod is deleted.

---

# 4.2. Configure the KServe Model Runtime

KServe needs a serving runtime capable of loading the sklearn model.

A custom `ClusterServingRuntime` is used for HousePred.

Create `serving-runtime.yaml`:

```yaml
apiVersion: serving.kserve.io/v1alpha1
kind: ClusterServingRuntime
metadata:
  name: kserve-sklearnserver
  annotations:
    serving.kserve.io/server-type: sklearnserver
spec:
  annotations:
    prometheus.kserve.io/port: '8080'
    prometheus.kserve.io/path: "/metrics"
  supportedModelFormats:
    - name: sklearn
      version: "1"
      autoSelect: true
      priority: 1
  protocolVersions:
    - v1
    - v2
  containers:
    - name: kserve-container
      image: kserve/sklearnserver:latest
      args:
        - --model_name={{.Name}}
        - --model_dir=/mnt/models
        - --http_port=8080
      securityContext:
        allowPrivilegeEscalation: false
        privileged: false
        runAsNonRoot: true
        capabilities:
          drop:
            - ALL
      resources:
        requests:
          cpu: "250m"
          memory: 512Mi
        limits:
          cpu: "500m"
          memory: 1Gi
```

Apply it:

```bash
kubectl apply -f serving-runtime.yaml
```

Verify:

```bash
kubectl get clusterservingruntime
```

The runtime is responsible for:

* Selecting `sklearnserver`
* Supporting the `sklearn` model format
* Loading the model from `/mnt/models`
* Exposing the HTTP inference server on port `8080`

The runtime should be created **before** the `InferenceService`.

Otherwise KServe may report:

```text
No runtime found to support specified framework/version
```

or:

```text
no runtime found to support predictor with model type: {sklearn <nil>}
```

---

# 4.3 Create the InferenceService

The `InferenceService` connects the HousePred model, storage, and serving runtime.

Create `inference-service.yaml`:

```yaml
apiVersion: serving.kserve.io/v1beta1
kind: InferenceService
metadata:
  name: house-model
  namespace: kserve
spec:
  predictor:
    model:
      modelFormat:
        name: sklearn
      storageUri: pvc://kserve-model-pvc
      resources:
        requests:
          cpu: "250m"
          memory: "512Mi"
        limits:
          cpu: "500m"
          memory: "1Gi"
```

Apply it:

```bash
kubectl apply -f inference-service.yaml
```

Check the InferenceService:

```bash
kubectl get inferenceservice house-model -n kserve
```

Inspect the complete status:

```bash
kubectl describe inferenceservice house-model -n kserve
```

A successful deployment should show:

```text
Deployment Mode: Standard
PredictorReady: True
Ready: True
Active Model State: Loaded
Target Model State: Loaded
```

---

# 4.4 KServe Predictor Resource Lifecycle

In Standard mode, KServe creates normal Kubernetes workload resources for the predictor.

The lifecycle is:

```text
InferenceService
      ↓
KServe Controller
      ↓
Deployment
      ↓
ReplicaSet
      ↓
Predictor Pod
      ↓
Serving Runtime
      ↓
sklearnserver
```

The predictor pod contains the KServe sklearn serving container.

Unlike the Knative deployment, there is no:

* Knative Service
* Knative Revision
* KPA
* queue-proxy
* Kourier

The predictor is a normal Kubernetes workload.

The generated predictor service can be inspected with:

```bash
kubectl get svc -n kserve
```

For HousePred, the predictor service is:

```text
house-model-predictor
```

Its internal Kubernetes DNS name is:

```text
house-model-predictor.kserve.svc.cluster.local
```

---

# 5. Test the Model

The Standard deployment was tested from inside the Kubernetes cluster using a temporary curl pod.

Create the test pod:

```bash
kubectl run curl-test \
  --image=curlimages/curl:8.10.1 \
  --rm -it \
  --restart=Never \
  -- sh
```

Inside the pod, check model readiness:

```bash
curl http://house-model-predictor.kserve.svc.cluster.local/v1/models/house-model
```

Expected response:

```json
{"name":"house-model","ready":true}
```

The model is now ready to receive predictions.

## 5.1 Send a Prediction Request

Send a prediction request:

```bash
curl -X POST \
  http://house-model-predictor.kserve.svc.cluster.local/v1/models/house-model:predict \
  -H "Content-Type: application/json" \
  -d '{
    "instances": [
      [5.0, 34.0, -118.0, 5.5, 30.0]
    ]
  }'
```

The successful response was:

```json
{"predictions":[2.5194516190616127]}
```

This confirms that:

* the predictor pod is running
* `sklearnserver` loaded the model
* the PVC is accessible
* the model is ready
* KServe is accepting prediction requests
* the HousePred model produced a prediction

The test uses the internal Kubernetes ClusterIP service. External ingress was not part of this Standard deployment test.

---

# 5.2 Request Flow

The Standard request flow is:

```text
Internal Client
      ↓
Kubernetes ClusterIP Service
      ↓
HousePred Predictor Pod
      ↓
Serving Runtime
      ↓
sklearnserver
      ↓
HousePred Model
      ↓
Prediction
```

For the tested deployment only, the request enters through:

```text
house-model-predictor.kserve.svc.cluster.local
```

The Kubernetes Service routes the request to the predictor pod.

The sklearnserver process receives the request and executes the HousePred model.

---

# 6. Component Responsibilities

| Component             | Responsibility                                            |
| --------------------- | --------------------------------------------------------- |
| Kubernetes            | Runs the serving workloads                                |
| cert-manager          | Provides certificate-related resources required by KServe |
| KServe                | Provides the Kubernetes-native model serving abstraction  |
| InferenceService      | Declares which model should be served                     |
| ClusterServingRuntime | Defines the sklearn serving runtime                       |
| sklearnserver         | Loads and serves the sklearn model                        |
| PVC                   | Stores the HousePred model artifact                       |
| Kubernetes Service    | Provides internal networking to the predictor             |

The key separation is:

```text
InferenceService
    → WHAT model to serve

ClusterServingRuntime
    → HOW the model is served

PVC
    → WHERE the model artifact is stored

Kubernetes
    → WHERE the predictor workload runs
```

---

# 7. Standard Deployment Behavior

KServe Standard mode uses normal Kubernetes serving resources.

The predictor runs as a normal Kubernetes workload rather than using Knative request-driven autoscaling.

The tested architecture is:

```text
InferenceService
      ↓
Deployment
      ↓
ReplicaSet
      ↓
Predictor Pod
      ↓
ClusterIP Service
```

There is no Knative scale-to-zero behavior in this deployment.

There is also no Knative scale-from-zero or KPA-based request autoscaling.

Kubernetes autoscaling mechanisms such as HPA can be configured separately if required, but they are not part of this deployment.

---

# 8. Standard vs Knative KServe

The two KServe deployment modes use different serving infrastructure.

## KServe Standard

```text
InferenceService
      ↓
KServe Controller
      ↓
Kubernetes Deployment
      ↓
ReplicaSet
      ↓
Predictor Pod
      ↓
Kubernetes Service
```

## KServe + Knative

```text
InferenceService
      ↓
KServe Controller
      ↓
Knative Service
      ↓
Knative Revision
      ↓
Pod
```

Kourier provides the networking/ingress layer for the Knative deployment.

The Standard deployment does not require:

* Knative Operator
* Knative Serving
* Kourier
* KPA
* Knative Service
* Knative Revision
* queue-proxy
* scale-to-zero
* scale-from-zero

The Knative deployment adds the serverless layer needed for request-driven scaling and scale-to-zero.

The Standard deployment instead relies on normal Kubernetes workload and networking primitives.

KServe Standard can use Kubernetes networking or ingress solutions such as Istio or Contour when they are available and configured in the cluster.

Unlike the Knative deployment, this does not require Knative Serving or Kourier.

---

# 9. Verify Standard Deployment

The deployment mode can be verified through the InferenceService:

```bash
kubectl describe inferenceservice house-model -n kserve
```

The status should contain:

```text
Deployment Mode: Standard
```

The predictor should be ready:

```text
PredictorReady: True
Ready: True
```

The model should be loaded:

```text
Active Model State: Loaded
Target Model State: Loaded
```

The predictor service can be inspected with:

```bash
kubectl get svc -n kserve
```

The predictor pod can be inspected with:

```bash
kubectl get pods -n kserve
```

A successful deployment has a running predictor pod similar to:

```text
house-model-predictor-<replicaset>-<pod>   1/1   Running
```

---

# 10. Final Architecture

The completed Standard architecture is:

```text
HousePred
    │
    ▼
linear_regression_model.joblib
    │
    ▼
PersistentVolumeClaim
    │
    ▼
KServe InferenceService
    │
    ▼
KServe Controller
    │
    ▼
Kubernetes Deployment
    │
    ▼
ReplicaSet
    │
    ▼
Predictor Pod
    │
    ▼
Serving Runtime
    │
    ▼
sklearnserver
    │
    ▼
Kubernetes ClusterIP Service
    │
    ▼
Prediction
```

The complete request path is:

```text
Client
  ↓
house-model-predictor
  ↓
Predictor Pod
  ↓
Serving Runtime
  ↓
sklearnserver
  ↓
HousePred
  ↓
Prediction
```

---

# 11. HousePred in the Serving Stack

HousePred can be deployed through different serving approaches.

The progression is:

```text
HousePred
   ↓
FastAPI
   ↓
Custom model API
```

```text
HousePred
   ↓
BentoML
   ↓
Model serving framework
```

```text
HousePred
   ↓
KServe Standard
   ↓
Kubernetes-native model serving
```

```text
HousePred
   ↓
KServe + Knative
   ↓
Kubernetes-native serverless model serving
```

The Standard deployment focuses on Kubernetes-native model serving without adding a serverless serving layer.

The Knative deployment adds Knative Serving and Kourier to provide request-driven serverless behavior.

---

# 12. Final Mental Model

The simplest way to understand the Standard deployment is:

```text
You declare
    │
    ├── ClusterServingRuntime
    │     → HOW the model is served
    │
    ├── PVC
    │     → WHERE the model is stored
    │
    └── InferenceService
          → WHAT model to serve
                │
                ▼
              KServe
                │
                ▼
        Kubernetes Deployment
                │
                ▼
           Predictor Pod
                │
                ▼
         Serving Runtime
                │
                ▼
           sklearnserver
                │
                ▼
              Model
```

The core idea is:

> **KServe defines the model-serving resources, the ClusterServingRuntime defines the serving runtime, the PVC provides the model artifact, and Kubernetes runs the resulting predictor workload.**

In Standard mode, the serving workload is a normal Kubernetes deployment.

In the separate Knative mode, KServe integrates with Knative to add serverless request-driven behavior.
