# KServe + Knative + Kourier — Setup Guide

This guide documents the KServe **Knative/serverless** deployment that was actually implemented for HousePred.

The project did **not** implement KServe Standard deployment. Standard mode is discussed in the main architecture README, but this guide covers the Knative path only.

The completed architecture is:

```text
HousePred model
      ↓
PersistentVolumeClaim
      ↓
KServe InferenceService
      ↓
Knative Serving
      ↓
Kourier
      ↓
Kubernetes
```

The important feature demonstrated is **scale-to-zero**.

---

# 1. Prerequisites

Required:

* Docker Desktop
* Docker Desktop Kubernetes
* `kubectl`
* Helm
* Docker Desktop Kubernetes with sufficient CPU/memory

Verify:

```bash
kubectl version --client
helm version
kubectl get nodes
```

---

# 2. Install cert-manager

Knative Operator and related components require certificate management.

Install cert-manager using the version appropriate for the project environment.

After installation, verify:

```bash
kubectl get pods -n cert-manager
```

The cert-manager components should become `Running`.

---

# 3. Install the Knative Operator

The project uses the Knative Operator to manage Knative Serving.

After installation:

```bash
kubectl get pods -n knative-operator
```

Expected components include:

```text
knative-operator
operator-webhook
```

The operator manages the Knative custom resources.

The important distinction is:

```text
Knative Operator
        ↓
manages
        ↓
Knative Serving
```

The Operator itself is not the request router or autoscaler.

---

# 4. Install Knative Serving

The project defines Knative Serving through:

```text
kserve-knative-serving.yaml
```

The resulting architecture contains Knative Serving components responsible for:

* Serving revisions
* Routing
* Activation
* Autoscaling
* Scale-to-zero

Check:

```bash
kubectl get knativeserving -n knative-serving
```

The resource should eventually report:

```text
READY=True
```

---

# 5. Install Kourier

The project uses Kourier rather than Istio as the Knative networking layer.

Install the matching Kourier release:

```bash
kubectl apply -f https://github.com/knative-extensions/net-kourier/releases/download/knative-v1.20.0/kourier.yaml
```

Verify:

```bash
kubectl get pods -n kourier-system
```

The important components are:

```text
3scale-kourier-gateway
net-kourier-controller
```

Kourier provides networking/ingress.

It is not responsible for scale-to-zero.

---

# 6. Configure Knative to Use Kourier

The Knative Serving configuration must use Kourier as its ingress class.

The project configured:

```text
kourier.ingress.networking.knative.dev
```

The Knative configuration was patched with:

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

Wait until:

```text
READY=True
```

---

# 7. KServe Installation

KServe was installed using Helm.

Create the KServe namespace and install the CRDs:

```bash
helm install kserve-crd \
  oci://ghcr.io/kserve/charts/kserve-crd \
  --version v0.20.0 \
  --namespace kserve \
  --create-namespace
```

Install KServe resources in Knative mode:

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

The project used:

```text
KServe v0.20.0
```

---

# 8. Configure KServe for Kourier

KServe's default serverless networking configuration assumes Istio-related resources.

Because this project uses Kourier, the KServe configuration disables KServe's Istio VirtualService handling:

```yaml
disableIstioVirtualHost: true
```

This is important because:

```text
KServe
  ↓
Knative
  ↓
Kourier
```

is the networking path used here.

Istio is not installed as the ingress layer for this deployment.

---

# 9. Kubernetes Model Storage

The model is stored on a Kubernetes PersistentVolume.

The project uses a PVC:

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
kubectl apply -f kserve-model-pvc.yaml
```

Check:

```bash
kubectl get pvc -n kserve
```

The PVC should reach:

```text
Bound
```

Docker Desktop provides the `hostpath` StorageClass used by this local cluster.

---

# 10. Load the Model

For this local setup, a temporary loader Pod was used to mount the PVC.

The loader mounts:

```text
kserve-model-pvc
        ↓
/mnt/models
```

The model file:

```text
linear_regression_model.joblib
```

was copied into the mounted volume.

Because Git Bash on Windows can rewrite Kubernetes paths, the copy command used:

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

The expected file is:

```text
linear_regression_model.joblib
```

The temporary loader Pod can then be deleted.

The model remains on the PVC.

---

# 11. Install the KServe Scikit-Learn Runtime

KServe's `InferenceService` needs a runtime capable of loading the model format.

The project installed the KServe scikit-learn runtime:

```bash
curl -L -o kserve-sklearnserver.yaml \
  https://raw.githubusercontent.com/kserve/kserve/v0.20.0/config/runtimes/kserve-sklearnserver.yaml
```

Apply:

```bash
kubectl apply -f kserve-sklearnserver.yaml
```

Verify:

```bash
kubectl get clusterservingruntime
```

The runtime uses:

```text
kserve/sklearnserver:latest
```

The important point is that the runtime provides the model-serving container. The project does not need to run the FastAPI application for this KServe deployment.

---

# 12. Resource Requests

The initial runtime configuration requested:

```text
CPU:    1
Memory: 2Gi
```

On the Docker Desktop Kubernetes node, available resources were already heavily allocated.

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

This allowed the model-serving Pod to be scheduled in the local Docker Desktop cluster.

This is a local-cluster scheduling consideration, not a KServe requirement that every production deployment use these exact values.

---

# 13. Create the InferenceService

The HousePred model is represented by an `InferenceService`.

The project uses:

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
kubectl apply -f kserve-housepred-model.yaml
```

The important setting is:

```yaml
minReplicas: 0
```

This allows the Knative-backed deployment to scale the model down to zero when idle.

---

# 14. KServe → Knative Resources

KServe creates the serving resources needed for the predictor.

Check:

```bash
kubectl get inferenceservice -n kserve
```

Then inspect the generated Knative resources:

```bash
kubectl get configuration -n kserve
kubectl get revision -n kserve
kubectl get route -n kserve
kubectl get service -n kserve
```

The resulting structure is approximately:

```text
InferenceService
      ↓
Knative Configuration
      ↓
Knative Revision
      ↓
Knative Route
      ↓
Knative Service
      ↓
Predictor Pod
```

The predictor revision can have:

```text
ACTUAL REPLICAS: 0
DESIRED REPLICAS: 0
```

when idle.

That is the expected scale-to-zero state.

---

# 15. Verify the KServe Service

The generated predictor Service in this Kourier configuration is backed by:

```text
kourier-internal.knative-serving.svc.cluster.local
```

The project intentionally disables KServe's Istio VirtualService handling because Kourier is the selected networking layer.

---

# 16. Test the Model Internally

A temporary curl Pod can be used to test the service from inside Kubernetes:

```bash
kubectl run curl \
  --rm -it \
  --restart=Never \
  --image=curlimages/curl \
  -- sh
```

Inside the Pod:

```bash
curl -X POST \
  http://house-model-predictor.kserve.svc.cluster.local/v1/models/house-model:predict \
  -H "Content-Type: application/json" \
  -d '{"instances":[[8.3252,37.88,-122.23,6.9841,41.0]]}'
```

The completed deployment returned:

```json
{"predictions":[4.080089668998603]}
```

The prediction is the same as the FastAPI and BentoML implementations because the underlying model is the same.

---

# 17. Observe Scale-to-Zero

When the service is idle, the revision can reach:

```text
ACTUAL REPLICAS: 0
DESIRED REPLICAS: 0
```

Conceptually:

```text
                 No requests
                     │
                     ▼
                  0 Pods
```

When a request arrives:

```text
Request
   ↓
Kourier
   ↓
Knative
   ↓
Activator / autoscaling
   ↓
Predictor Pod
   ↓
KServe runtime
   ↓
Sklearn model
   ↓
Prediction
```

After the service becomes idle again:

```text
Predictor Pod
     ↓
   idle
     ↓
scale down
     ↓
   0 Pods
```

---

# 18. Cold Start vs Warm Request

The project demonstrated two different request paths.

### Cold request

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

This request is slower.

### Warm request

```text
Request
  ↓
Existing predictor Pod
  ↓
Loaded model
  ↓
Prediction
```

This request is faster.

The fundamental trade-off is:

> Scale-to-zero reduces idle resource consumption at the cost of cold-start latency.

---

# 19. KServe Standard Mode

**KServe Standard mode was not implemented in this project.**

It was studied conceptually as the alternative to Knative mode.

The implemented deployment is:

```text
KServe
  ↓
Knative
  ↓
Kourier
  ↓
scale-to-zero
```

Standard mode would instead use ordinary Kubernetes deployment mechanisms and does not provide the same Knative request-driven scale-to-zero behavior.

Therefore this repository should not claim that both KServe deployment modes were implemented.

---

# 20. Final Architecture

The completed HousePred KServe deployment is:

```text
                         Client
                           │
                           ▼
                        Kourier
                           │
                           ▼
                     Knative Serving
                           │
                    request-driven KPA
                           │
                    ┌──────┴──────┐
                    │             │
                 1+ Pods        0 Pods
                    │          when idle
                    │
                    ▼
               KServe Predictor
                    │
                    ▼
             sklearnserver runtime
                    │
                    ▼
              HousePred model
                    │
                    ▼
                Prediction
```

The major components have separate responsibilities:

| Component        | Responsibility                                |
| ---------------- | --------------------------------------------- |
| Kubernetes       | Container orchestration and resources         |
| KServe           | ML model-serving abstraction                  |
| InferenceService | Declarative model-serving resource            |
| Knative          | Serverless serving and request-driven scaling |
| KPA              | Knative autoscaling                           |
| Kourier          | Networking / ingress                          |
| sklearnserver    | Scikit-learn model-serving runtime            |
| PVC              | Model artifact storage                        |

This is the most infrastructure-heavy serving architecture implemented in HousePred, but it demonstrates the largest set of ML-serving platform capabilities, particularly request-driven autoscaling and scale-to-zero.
