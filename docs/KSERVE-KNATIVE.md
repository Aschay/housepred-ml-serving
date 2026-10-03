# KServe + Knative + Kourier — Setup Guide

This guide documents the **KServe + Knative serverless deployment** implemented for HousePred.

The deployment demonstrates:

* Kubernetes-native model serving with KServe
* Knative-based serverless deployment
* Kourier networking
* request-driven autoscaling
* scale-to-zero
* scale-from-zero
* cold-start vs warm-request behavior

The high-level architecture is:

```text
                         Client
                           │
                           ▼
                        Kourier
                           │
                           ▼
                    Knative Serving
                           │
                           ▼
                    KServe Predictor
                           │
                           ▼
                    sklearnserver
                           │
                           ▼
                     HousePred
                           │
                           ▼
                       Prediction
```

The model artifact is stored separately:

```text
PersistentVolume
       │
       ▼
      PVC
       │
       ▼
linear_regression_model.joblib
       │
       ▼
KServe Predictor
```

---

# 1. Prerequisites

## Requirements

* A container runtime
* A Kubernetes cluster
* `kubectl`
* Helm
* Sufficient CPU and memory for Kubernetes, Knative, KServe, and the model-serving runtime

## Local Environment

The deployment was implemented using:

* Docker Desktop
* Docker Desktop Kubernetes
* Docker Desktop `hostpath` storage
* Windows
* Git Bash

Verify the environment:

```bash
kubectl version --client
helm version
kubectl get nodes
```

The CPU and memory values used later are local resource choices for the Docker Desktop cluster. They are not universal KServe requirements.

---

# 2. Serving Infrastructure

The deployment uses several independent components:

```text
cert-manager
      │
      └── certificate management

Knative Operator
      │
      └── manages Knative installation/lifecycle

Knative Serving
      │
      ├── serverless serving
      ├── Revisions
      ├── routing
      └── autoscaling

Kourier
      │
      └── Knative networking

KServe
      │
      └── ML model-serving abstraction
```

Helm is used to install KServe in this project. It does **not** install the Knative Operator or Knative Serving.

---

## 2.1 Install cert-manager

The environment uses **cert-manager v1.21.2**.

Install:

```bash
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.21.2/cert-manager.yaml
```

Verify:

```bash
kubectl get pods -n cert-manager
```

The cert-manager components should become:

```text
Running
```

cert-manager provides certificate-management infrastructure used by the serving stack.

Its responsibility is separate from Knative:

```text
cert-manager
      ↓
certificate management

Knative Operator
      ↓
Knative component lifecycle

Knative Serving
      ↓
serverless serving and autoscaling
```

---

## 2.2 Install the Knative Operator

The project uses **Knative Operator v1.20.0**.

Install:

```bash
kubectl apply -f https://github.com/knative/operator/releases/download/knative-v1.20.0/operator.yaml
```

Verify:

```bash
kubectl get pods -n knative-operator
```

The Operator is responsible for managing Knative custom resources and their corresponding Knative components.

---

## 2.3 Install Knative Serving

The repository contains:

```text
knative-serving.yaml
```

This creates the `KnativeServing` custom resource:

```yaml
apiVersion: operator.knative.dev/v1beta1
kind: KnativeServing
metadata:
  name: knative-serving
  namespace: knative-serving
```

Apply:

```bash
kubectl apply -f knative-serving.yaml
```

Verify:

```bash
kubectl get knativeserving -n knative-serving
```

Expected:

```text
NAME              VERSION   READY
knative-serving   1.20.0    True
```

Knative Serving provides the infrastructure for:

* serving
* Revisions
* routing
* activation
* autoscaling
* scale-to-zero

A networking implementation is still required.

---

## 2.4 Install Kourier

This deployment uses **Kourier v1.20.0** as the networking implementation for Knative Serving.

Install:

```bash
kubectl apply -f https://github.com/knative-extensions/net-kourier/releases/download/knative-v1.20.0/kourier.yaml
```

Verify:

```bash
kubectl get pods -n kourier-system
```

Important components include:

```text
3scale-kourier-gateway
net-kourier-controller
```

Kourier provides the networking/ingress layer for Knative.

---

## 2.5 Configure Knative to Use Kourier

The selected ingress class is:

```text
kourier.ingress.networking.knative.dev
```

Apply the configuration:

```bash
kubectl patch knativeserving knative-serving \
  -n knative-serving \
  --type=merge \
  -p '{"spec":{"ingress":{"kourier":{"enabled":true}},"config":{"network":{"ingress-class":"kourier.ingress.networking.knative.dev"}}}}'
```

Verify:

```bash
kubectl get knativeserving -n knative-serving
```

Wait for:

```text
READY=True
```

The important networking relationship is:

```text
Client
  ↓
Kourier
  ↓
Knative networking
  ↓
Knative Route / Revision
  ↓
KServe predictor
```

### KServe and Istio

Because this deployment uses Kourier instead of Istio, the KServe serverless configuration uses:

```yaml
disableIstioVirtualHost: true
```

This prevents KServe's serverless configuration from relying on the Istio VirtualHost path while Kourier is the selected Knative networking implementation.

---

# 3. Install KServe

KServe uses Helm **v0.20.0** in this deployment.

## 3.1 Install KServe CRDs

```bash
helm install kserve-crd \
  oci://ghcr.io/kserve/charts/kserve-crd \
  --version v0.20.0 \
  --namespace kserve \
  --create-namespace
```

The CRD release provides the Kubernetes custom resource definitions required by KServe.

## 3.2 Install KServe Resources

```bash
helm install kserve-resources \
  oci://ghcr.io/kserve/charts/kserve-resources \
  --version v0.20.0 \
  --namespace kserve \
  --set kserve.controller.deploymentMode=Knative \
  --wait
```

Verify:

```bash
helm list -n kserve
```

The important configuration is:

```text
deploymentMode=Knative
```

This tells KServe to use the Knative deployment path for predictors.

The resulting relationship is:

```text
KServe
  ↓
deploymentMode=Knative
  ↓
Knative-backed predictor
```

---

# 4. The HousePred Serving Pipeline

Before creating the model resources, it is useful to understand the three things being declared.

```text
1. Serving Runtime
   serving-runtime.yaml
   ↓
   HOW to run the model

2. Model Storage
   pvc.yaml + model-loader
   ↓
   WHERE the model is

3. InferenceService
   inference-service.yaml
   ↓
   WHAT model to serve
```

These are combined by KServe:

```text
Serving Runtime ──────── HOW
        │
        │
Model Storage ────────── WHERE
        │
        │
InferenceService ─────── WHAT
        │
        ▼
      KServe
        │
        ▼
  Knative deployment
        │
        ▼
 Kubernetes workload
```

This is the central mental model for the deployment.

---

# 5. Prepare Model Storage

The trained model is stored separately from the KServe runtime.

The model artifact is:

```text
linear_regression_model.joblib
```

For this local deployment, the model is stored in a Kubernetes PersistentVolume through a PersistentVolumeClaim.

## 5.1 Create the PVC

Repository file:

```text
pvc.yaml
```

Configuration:

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
  storageClassName: hostpath
```

Apply:

```bash
kubectl apply -f pvc.yaml
```

Check:

```bash
kubectl get pvc -n kserve
```

The PVC should reach:

```text
Bound
```

Docker Desktop Kubernetes provides the `hostpath` StorageClass used by this local setup.

The storage relationship is:

```text
PersistentVolume
      ↓
PVC
      ↓
model storage
```

---

## 5.2 Load the Model into the PVC

A temporary Pod is used to copy the existing model into the PVC.

Repository file:

```text
model-loader.yaml
```

Apply:

```bash
kubectl apply -f model-loader.yaml
```

The loader mounts the PVC at:

```text
/mnt/models
```

The model is copied into:

```text
/mnt/models/linear_regression_model.joblib
```

Because the project is operated from Git Bash on Windows, MSYS path conversion must be disabled for `kubectl cp`:

```bash
MSYS_NO_PATHCONV=1 kubectl cp \
  model/linear_regression_model.joblib \
  kserve/model-loader:/mnt/models/linear_regression_model.joblib
```

Verify:

```bash
MSYS_NO_PATHCONV=1 kubectl exec \
  -n kserve model-loader \
  -- ls -lh /mnt/models
```

Expected:

```text
linear_regression_model.joblib
```

Once the model has been copied successfully, the temporary loader can be deleted:

```bash
kubectl delete -f model-loader.yaml
```

The model remains in the persistent volume.

Final storage relationship:

```text
PersistentVolume
      ↓
PVC: kserve-model-pvc
      ↓
/mnt/models
      ↓
linear_regression_model.joblib
```

The loader is only used to populate the persistent storage.

---

# 6. Configure the KServe Model Runtime

HousePred uses a **Scikit-Learn** model, so the `InferenceService` needs a runtime capable of loading and serving a Scikit-Learn model.

Repository file:

```text
serving-runtime.yaml
```

Apply:

```bash
kubectl apply -f serving-runtime.yaml
```

Verify:

```bash
kubectl get clusterservingruntime
```

The configured runtime uses:

```text
kserve/sklearnserver:latest
```

The runtime relationship is:

```text
KServe
  ↓
ClusterServingRuntime
  ↓
kserve-sklearnserver
  ↓
Scikit-Learn model
```

The runtime defines **HOW** the model is served.

---

## 6.1 Runtime Resources

The initial runtime configuration requested:

```text
CPU:    1
Memory: 2Gi
```

This was too expensive for the available Docker Desktop Kubernetes node because the node was already running:

* Kubernetes
* cert-manager
* Knative Operator
* Knative Serving
* Kourier
* KServe

The runtime was therefore reduced to:

```yaml
resources:
  requests:
    cpu: "250m"
    memory: 512Mi
  limits:
    cpu: "500m"
    memory: 1Gi
```

These are **local-cluster resource choices**, not universal KServe requirements.

---

# 7. Create the InferenceService

The HousePred model is represented by a KServe `InferenceService`.

Repository file:

```text
inference-service.yaml
```

Configuration:

```yaml
apiVersion: serving.kserve.io/v1beta1
kind: InferenceService
metadata:
  name: house-model
  namespace: kserve
spec:
  predictor:
    minReplicas: 0
    model:
      modelFormat:
        name: sklearn
      storageUri: pvc://kserve-model-pvc
```

Apply:

```bash
kubectl apply -f inference-service.yaml
```

Check:

```bash
kubectl get inferenceservice -n kserve
```

The important settings are:

```yaml
minReplicas: 0
```

and:

```yaml
storageUri: pvc://kserve-model-pvc
```

`minReplicas: 0` allows the Knative-backed predictor to scale to zero.

The `storageUri` tells KServe where the model artifact is located.

The model-serving relationship is:

```text
InferenceService
      │
      ├── model format: sklearn
      │
      └── storageUri
             ↓
        kserve-model-pvc
             ↓
linear_regression_model.joblib
```

---

# 8. KServe Predictor Resource Lifecycle

KServe reconciles the `InferenceService` and creates the resources required to run the predictor.

The lifecycle can be simplified as:

```text
InferenceService
      ↓
KServe Controller
      ↓
Knative Service
      ↓
Revision
      ↓
Deployment
      ↓
ReplicaSet
      ↓
Pod
```

This is a **controller reconciliation process**, not a literal compilation step.

When the predictor is running, the Pod contains two containers:

```text
Predictor Pod
│
├── sklearnserver
│     ├── KServe model-serving runtime
│     ├── loads the model
│     └── performs inference
│
└── queue-proxy
      ├── Knative sidecar
      └── participates in traffic/concurrency handling
```

Therefore:

```text
2/2 Running
```

means **one Pod containing two containers**, not two predictor replicas.

The `sklearnserver` container is responsible for model inference.

The `queue-proxy` is part of the Knative serving infrastructure and participates in request handling and concurrency measurement.

---

# 9. Test the Model

A temporary curl Pod can be used to test the service from inside the Kubernetes cluster.

Start the Pod:

```bash
kubectl run curl \
  --rm -it \
  --restart=Never \
  --image=curlimages/curl \
  -- sh
```

Inside the Pod, send a prediction request:

```bash
curl -X POST \
  -H "Host: house-model-predictor.kserve.svc.cluster.local" \
  -H "Content-Type: application/json" \
  -d '{"instances":[[8.3252,37.88,-122.23,6.9841,41.0]]}' \
  http://kourier-internal.knative-serving.svc.cluster.local/v1/models/house-model:predict
```

The request uses the Kourier internal service and the Knative/KServe host name so that it follows the same routing path used by the Knative deployment.

The model being served is the same trained HousePred model used by the other serving implementations.

---

# 10. Request Flow

The actual request path is separate from the autoscaling/control path.

## Request Path

```text
Client
  ↓
Kourier
  ↓
Knative Route
  ↓
Revision
  ↓
Revision Service
  ↓
Predictor Pod
  ↓
queue-proxy
  ↓
sklearnserver
  ↓
HousePred model
  ↓
Prediction
```

## Scaling / Control Path

```text
                    Knative Serving
                           │
                           ▼
                          KPA
                           │
                           ▼
                scaling decisions
                           │
                    ┌──────┴──────┐
                    │             │
                  scale up      scale down
                    │             │
                    ▼             ▼
                 Pods          0 Pods
```

KPA is therefore **not a request hop**. It observes serving activity and makes scaling decisions.

---

# 11. Component Responsibilities

| Component             | Responsibility                                                          |
| --------------------- | ----------------------------------------------------------------------- |
| Kubernetes            | Container orchestration, scheduling, storage, and networking primitives |
| KServe                | Kubernetes-native ML-serving abstraction                                |
| InferenceService      | Declarative definition of the model to serve                            |
| ClusterServingRuntime | Defines the model-serving runtime                                       |
| Knative Operator      | Installation and lifecycle management of Knative components             |
| Knative Serving       | Serverless serving, Revisions, routing, activation, and autoscaling     |
| KPA                   | Request/concurrency-driven autoscaling                                  |
| Kourier               | Knative networking / ingress                                            |
| sklearnserver         | Scikit-Learn model-serving runtime                                      |
| PVC                   | Persistent model artifact storage                                       |
| cert-manager          | Certificate-management infrastructure                                   |

The simplified responsibility model is:

```text
KServe
  ↓
ML-serving abstraction

Knative
  ↓
Serverless serving

KPA
  ↓
Request-driven scaling

Kourier
  ↓
Networking

sklearnserver
  ↓
Model inference

PVC
  ↓
Model storage
```

---

# 12. Scale-to-Zero

The predictor is configured with:

```yaml
minReplicas: 0
```

When there is no sustained traffic, Knative can scale the Revision down to zero.

The resulting state can be observed with:

```text
ACTUAL REPLICAS: 0
DESIRED REPLICAS: 0
```

Conceptually:

```text
No sustained traffic
        ↓
       KPA
        ↓
Scaling decision
        ↓
0 predictor Pods
```

When a new request arrives while the Revision is scaled to zero, Knative activates the Revision and starts the required workload.

```text
Request
   ↓
Kourier
   ↓
Knative
   ↓
Activation / scale-from-zero
   ↓
Predictor Pod starts
   ↓
KServe runtime
   ↓
Model
   ↓
Prediction
```

After the Revision becomes idle again:

```text
Predictor Pod
      ↓
    idle
      ↓
     KPA
      ↓
scale down
      ↓
   0 Pods
```

This request-driven scaling behavior is the main serverless capability demonstrated by the deployment.

---

# 13. Cold Start vs Warm Request

## Cold Request

When the predictor has scaled to zero:

```text
Request
   ↓
Knative activation
   ↓
Pod creation
   ↓
Container startup
   ↓
Model loading
   ↓
Prediction
```

The request experiences cold-start overhead.

## Warm Request

When the predictor Pod is already running:

```text
Request
   ↓
Existing predictor Pod
   ↓
Loaded model
   ↓
Prediction
```

The warm request avoids the scale-from-zero startup path.

The trade-off is:

```text
Scale-to-zero
     ↓
Lower idle resource usage
     +
Higher cold-start latency
```

---

# 14. Tune Knative Autoscaling

The Knative autoscaler configuration can be inspected with:

```bash
kubectl get configmap config-autoscaler \
  -n knative-serving \
  -o yaml
```

The relevant configuration used during the deployment included:

```yaml
stable-window: "60s"
scale-to-zero-grace-period: "30s"
scale-to-zero-pod-retention-period: "0s"
scale-down-delay: "0s"
```

For this local experiment, the stable window was changed from `60s` to `180s`:

```bash
kubectl patch configmap config-autoscaler \
  -n knative-serving \
  --type merge \
  -p '{"data":{"stable-window":"180s"}}'
```

Verify:

```bash
kubectl get configmap config-autoscaler \
  -n knative-serving \
  -o jsonpath='{.data.stable-window}{"\n"}'
```

Expected:

```text
180s
```

The `180s` value is a local tuning choice for observing the deployment. It is not a universal Knative requirement.

> Note: `config-autoscaler` is managed by the Knative Operator. A direct patch can be overwritten by Operator reconciliation. Persistent configuration should therefore be maintained through the `KnativeServing` configuration rather than treating the generated ConfigMap as the long-term source of truth.

---

# 15. Troubleshooting and Integration Notes

### Runtime Resource Pressure

The initial predictor resource configuration was too large for the available Docker Desktop node.

### Knative Networking

The deployment initially encountered networking configuration issues around the Istio path.

Kourier was selected as the final networking implementation:

```text
kourier.ingress.networking.knative.dev
```

Kourier was explicitly enabled in the `KnativeServing` configuration.

---

### KServe and Istio

Because Kourier is used instead of Istio, the KServe serverless configuration uses:

```yaml
disableIstioVirtualHost: true
```

This keeps the KServe serverless configuration aligned with the actual Knative networking implementation.

---

### Wdows Git Bash Path Conversion

# 16. Final Architecture

The completed HousePred deployment can be viewed as three related paths.

## Request Path

```text
                         Client
                           │
                           ▼
                        Kourier
                           │
                           ▼
                    Knative Route
                           │
                           ▼
                       Revision
                           │
                           ▼
                  Revision Service
                           │
                           ▼
                    Predictor Pod
                           │
                    ┌──────┴──────┐
                    │             │
              queue-proxy    sklearnserver
                                  │
                                  ▼
                           HousePred model
                                  │
                                  ▼
                              Prediction
```

## Scaling Path

```text
                    Knative Serving
                           │
                           ▼
                          KPA
                           │
                 ┌─────────┴─────────┐
                 │                   │
              scale up            scale down
                 │                   │
                 ▼                   ▼
              1+ Pods              0 Pods
```

## Model Storage Path

```text
PersistentVolume
      │
      ▼
     PVC
      │
      ▼
linear_regression_model.joblib
      │
      ▼
KServe Predictor
      │
      ▼
sklearnserver
```

---

# 17. HousePred in the Serving Stack

HousePred uses the same trained model across several serving approaches:

```text
FastAPI
   ↓
Application-level serving

BentoML
   ↓
ML-focused application serving

KServe
   ↓
Kubernetes-native ML serving

KServe + Knative
   ↓
Kubernetes-native ML serving
+
Serverless serving
+
Request-driven autoscaling
+
Scale-to-zero
+
Revision-based serving
```

The progression demonstrated by the project is therefore:

```text
Application serving
        ↓
ML-serving framework
        ↓
Kubernetes-native ML serving
        ↓
Kubernetes-native serverless ML serving
```

The architectural responsibilities are:

```text
KServe
    → ML-serving abstraction

Knative
    → serverless serving and autoscaling

Kourier
    → networking

KServe model runtime
    → model inference

PVC
    → model artifact storage
```

---

# 18. Final Mental Model

The simplest way to understand the complete deployment is:

```text
You declare
     │
     ├── Serving Runtime
     │      → HOW to run the model
     │
     ├── PVC + model-loader
     │      → WHERE the model is
     │
     └── InferenceService
            → WHAT model to serve
                    │
                    ▼
                  KServe
                    │
                    ▼
             Knative resources
             ├── Configuration
             ├── Revision
             ├── Service
             └── Route
                    │
                    ▼
                 Kubernetes
             ├── Deployment
             ├── ReplicaSet
             └── Pod
```

In one sentence:

> **KServe defines what model to serve and how to serve it, Knative provides the serverless execution and autoscaling behavior, Kourier provides networking, and Kubernetes runs the resulting workloads.**
