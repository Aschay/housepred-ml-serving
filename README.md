# ML Serving Architecture

HousePred is a small machine-learning serving project built to understand the different layers involved in deploying and serving ML models.

This is simple online synchronous inference: a client sends model inputs and receives a prediction in the same request.

The project keeps this inference pattern constant while exploring different ways to serve the same model: FastAPI + Docker, BentoML, KServe Standard, and KServe with Knative.

The same California Housing linear-regression model is served through several approaches:

* FastAPI + Docker
* BentoML
* KServe Standard on Kubernetes
* KServe with Knative on Kubernetes

## Setup Guides

- [FastAPI Deployment](docs/FASTAPI.md)
- [BentoML Deployment](docs/BENTOML.md)
- [KServe + Knative ](docs/KSERVE-KNATIVE.md)
- [KServe Standard](docs/KSERVE-STANDARD.md)

The goal is not to compare model quality. The goal is to understand the **serving abstractions, Kubernetes resources, networking, scaling, model storage, and deployment behavior** provided by each approach.

---

# Architecture

```text
                         ML SERVING

                             │

             ┌───────────────┴───────────────┐
             │                               │
       Application serving          Kubernetes-native
                                    ML serving
             │                               │
       ┌─────┴─────┐                       KServe
       │           │                         │
    FastAPI      BentoML               ┌─────┴─────┐
       +           +                   │           │
     Docker    OCI builder          Standard   Knative
       │           │                   │           │
       │           │                   │    Knative Serving
       │           │                   │      ┌────┼────┐
       │           │                   │      │    │    │
       │           │                   │     KPA Revisions Traffic
       │           │                   │           │
       │           │                   │        Kourier
       │           │                   │           │
       │           │                   │       networking
       │           │                   │
       └───────────┴───────────────────┴───────────┘
                             │
                             ▼
                         Kubernetes
```

Both KServe deployment modes run on Kubernetes:

* **Standard mode** uses Kubernetes resources directly.
* **Knative mode** uses Knative Serving on top of Kubernetes to provide serverless serving capabilities such as request-driven autoscaling, scale-to-zero, Revisions, and Revision traffic management.

FastAPI and BentoML can also be deployed to Kubernetes; their distinction here is the **serving abstraction**, not the underlying deployment platform.

---

# 1. FastAPI

FastAPI represents the most application-oriented approach in this project.

The developer builds the HTTP API, loads the model, performs preprocessing and inference, and defines the health and readiness behavior, providing flexibility and choice over the serving layer: endpoints, validation, logging, metrics, health checks, error handling, and containerization.

```text
Client

  │

  ▼

FastAPI

  │

  ├── /predict

  ├── /healthz

  └── /ready

  │

  ▼

ML model
```

The application is packaged into a Docker image with Docker.

FastAPI therefore provides the **application-level serving layer**, while Docker provides the container packaging.

### Typical project structure

```text
HousePred/

├── app/

│   └── main.py

├── model/

│   └── linear_regression_model.joblib

├── requirements.txt

└── Dockerfile
```

### Kubernetes

When deployed to Kubernetes, Kubernetes provides the infrastructure around the application:

```text
Kubernetes

   │

   ├── Deployment

   │      └── Pod

   │           └── readiness/liveness probes

   ├── Service

   └── HPA
```

The application remains responsible for the inference API and model execution.

---

# 2. BentoML

BentoML provides a more ML-focused serving abstraction.

Instead of manually implementing the complete serving layer, the model is exposed through a BentoML service:

```text
Client

  │

  ▼

BentoML

  │

  └── Service

          │

          ▼

       ML model
```

BentoML provides serving infrastructure around the model, including:

* HTTP serving
* generated API/OpenAPI documentation
* Swagger UI for interacting with the API
* built-in health endpoints such as `/livez`, `/readyz`, and `/healthz`
* built-in metrics
* configurable server/access logging
* tracing support
* model/inference monitoring and data collection

These capabilities are provided by BentoML's serving and observability infrastructure.

BentoML therefore provides more of the operational serving layer around the model instead of requiring the developer to build those pieces independently.

### Typical project structure

Conceptually, the project becomes:

```text
HousePred/

├── service.py

├── model/

│   └── linear_regression_model.joblib

└── bentofile.yaml
```

Bento is then containerized by BentoML into a container image. BentoML builds the deployable container image, eliminating the need to manually create and maintain a Dockerfile.

Unlike the manually defined FastAPI Docker image, the generated image includes the BentoML serving runtime and its dependencies, so its size depends on the selected runtime and packaged dependencies.

### Kubernetes

The resulting BentoML container can be deployed like another application:

```text
Kubernetes

   │

   ├── Deployment

   │      └── BentoML Pod

   │           └── readiness/liveness probes

   ├── Service

   └── HPA
```

The important distinction from FastAPI is the abstraction level:

```text
FastAPI

    → define the application serving layer using a web framework

BentoML

    → define the model service while BentoML provides

      more of the ML-serving infrastructure
```

---

# 3. KServe

KServe is a Kubernetes-native ML serving platform.

Instead of primarily thinking in terms of:

```text
Deployment → Pod → application
```

the developer works with an ML-serving abstraction such as:

```text
InferenceService
```

For example:

```text
InferenceService

      │

      ▼

   Predictor

      │

      ▼

  Model runtime

      │

      ▼

    Model
```

KServe's controller watches KServe resources and reconciles them into Kubernetes resources and the corresponding serving infrastructure.

KServe adds ML-serving abstractions and behavior on top of Kubernetes primitives.

```text
KServe

   │

   └── Kubernetes resources

          │

          ├── Pods

          ├── Deployments

          ├── Services

          ├── storage

          ├── networking

          └── autoscaling
```

---

## 3.1 KServe Standard Mode

KServe Standard mode uses standard Kubernetes resources without Knative.

Conceptually:

```text
                    Kubernetes

                        │

                      KServe

                        │

                InferenceService

                        │

           ┌────────────┴────────────┐
           │                         │

      Deployment                  Service

           │                         │

       Predictor                    │

           │                         │

         Model          Kubernetes networking
```

Standard mode can use Kubernetes networking infrastructure around the serving workload.

For example:

```text
Client

  │

  ▼

Ingress / Gateway API / networking implementation

  │

  ▼

Kubernetes Service

  │

  ▼

KServe predictor
```

KServe's current Standard documentation recommends Gateway API and also supports Kubernetes Ingress.

### Scaling

KServe Standard can use Kubernetes autoscaling mechanisms such as HPA, and KServe also supports KEDA for appropriate scaling configurations.

```text
Traffic

   │

   ▼

KServe predictor

   │

   ▼

Kubernetes HPA

   │

   ▼

Deployment replicas
```

---

## 3.2 KServe with Knative

KServe can use **Knative Serving as its deployment mode**.

KServe remains responsible for the ML-serving abstraction.

Knative provides the serverless serving infrastructure around the workload.

This adds capabilities such as:

* point-in-time, generally immutable Revisions
* request-driven autoscaling
* scale-to-zero
* scale-from-zero
* Revision traffic management
* traffic splitting

KServe with Knative also uses Knative's networking layer. In this project, **Kourier is used as the networking implementation**.

```text
KServe

   │

   ▼

Knative Serving

   │

   ├── KPA

   ├── Revisions

   ├── Traffic management

   │

   └── Knative networking

           │

           └── Kourier
```

Traffic splitting is also possible through Kubernetes networking mechanisms such as Gateway API, but Knative provides **Revision-aware traffic management as part of Knative Serving**.

---

## 3.2.1 KPA and Scale-to-Zero

Knative Serving uses the **Knative Pod Autoscaler (KPA)** by default.

KPA scales according to application traffic/concurrency rather than using Kubernetes HPA's CPU-utilization model. KPA supports concurrency and request-per-second based scaling.

```text
                HTTP traffic

                     │

                     ▼

                  Knative

                     │

                    KPA

                     │

         ┌───────────┴───────────┐
         │                       │

    low traffic             high traffic

         │                       │

      0 → 1 → 2              2 → 5 → 10
       replicas                replicas
```

When scale-to-zero is enabled, a Revision can have zero running Pods when it has no traffic.

A scale-to-zero system can introduce **cold-start latency** because the predictor must be brought back from zero before it can serve the request.

Scale-to-zero is specifically supported with KPA.

---

## 3.2.2 Revisions and Traffic Management

Knative introduces the concept of a **Revision**.

A Revision represents a point-in-time version of a Knative workload and is generally immutable.

```text
Knative Service

      │

      ├── Revision 1

      │

      ├── Revision 2

      │

      └── Revision 3
```

Knative can route traffic between these Revisions:

```text
                Knative Service

                      │

            ┌─────────┴─────────┐
            │                   │

       Revision 1          Revision 2

           90%                 10%
```

This provides Revision-aware traffic splitting and supports deployment patterns such as canary and blue/green rollouts.

Kubernetes networking can independently implement traffic splitting as well. For example, Gateway API `HTTPRoute` can distribute traffic between different Kubernetes Services using weights.

So:

```text
Kubernetes networking

    → can implement traffic splitting between Kubernetes workloads

Knative

    → provides Revision-aware traffic management

      as part of Knative Serving
```

---

## 3.3 Model Storage

The model can be stored using local Kubernetes storage or remote/object storage depending on the deployment.

In this project, the KServe deployments use **local Kubernetes persistent storage**:

```text
PersistentVolume

      │

      ▼

     PVC

      │

      ▼

KServe predictor

      │

      ▼

linear_regression_model.joblib
```

The PVC provides persistent storage for the model artifact.

The same model-storage concept applies to both KServe Standard and KServe with Knative.

KServe also supports remote/object-storage-based model artifacts depending on the runtime and storage configuration.

### Typical KServe project structure

```text
HousePred/

├── kserve/

│   ├── inference-service.yaml

│   ├── pvc.yaml

│   └── runtime.yaml

│

└── model/

    └── linear_regression_model.joblib
```

The files represent:

```text
inference-service.yaml

    → defines the KServe InferenceService

pvc.yaml

    → defines the PersistentVolumeClaim used for model storage

runtime.yaml

    → defines/configures the serving runtime when an explicit runtime

      configuration is needed

model/

    → contains the model artifact
```

The runtime YAML is optional when an already-available serving runtime can be referenced without additional runtime configuration.

---

# 4. ML Serving vs Large-Model Serving

The HousePred model is intentionally small.

```text
HousePred

   │

   └── sklearn linear regression
```

The same serving concepts can be applied to larger models, but large-model inference introduces additional concerns such as:

* GPU scheduling
* GPU memory
* model loading time
* batching
* concurrency
* model parallelism
* tensor parallelism
* specialized inference runtimes

Therefore, a small sklearn model keeps the focus on **serving architecture rather than GPU/model complexity**.

---

# 5. Comparing the Serving Approaches

The comparison here focuses on **what each serving approach adds**, rather than treating Kubernetes itself as one of the competing serving approaches.

|                           | FastAPI                      | BentoML                        | KServe Standard              | KServe + Knative                    |
| ------------------------- | ---------------------------- | ------------------------------ | ---------------------------- | ----------------------------------- |
| Primary abstraction       | HTTP application             | ML service                     | ML serving resource          | ML serving + serverless serving     |
| Model-serving abstraction | Application code             | Bento service                  | InferenceService             | InferenceService                    |
| HTTP serving              | FastAPI application          | Built in                       | Runtime/platform dependent   | Runtime/platform dependent          |
| API documentation         | FastAPI/OpenAPI              | OpenAPI + Swagger UI           | Serving-runtime dependent    | Serving-runtime dependent           |
| Health endpoints          | Application-defined          | Built in                       | Serving infrastructure       | Serving infrastructure              |
| Metrics/observability     | Add/configure                | Built-in capabilities          | KServe/Kubernetes ecosystem  | KServe/Knative/Kubernetes ecosystem |
| Container packaging       | Docker                       | BentoML + OCI builder          | Serving runtime/container    | Serving runtime/container           |
| Kubernetes support        | Optional                     | Optional                       | Native                       | Native                              |
| Main value                | Flexible application serving | ML-focused serving abstraction | Kubernetes-native ML serving | KServe + serverless serving         |

KServe Standard uses Kubernetes-native serving and HPA, while KServe with Knative uses serverless, request-driven serving with KPA, scale-to-zero, and Revisions.

---

# 6. Responsibility Boundaries

The most important architectural distinction in this project is **who provides which capability**.

### KServe

Provides the Kubernetes-native ML-serving layer:

```text
InferenceService

Model-serving abstractions

Serving runtimes

Model storage integration

Predictor / transformer / explainer concepts

Inference protocols

ML-serving lifecycle/reconciliation
```

KServe's controller reconciles KServe resources and manages the corresponding Kubernetes serving resources and configuration.

### KServe with Knative

Adds serverless serving capabilities on Kubernetes:

```text
Services

Revisions

Request-driven autoscaling

KPA

Scale-to-zero

Scale-from-zero

Revision traffic management
```

HPA is a Kubernetes autoscaling mechanism while KPA is Knative's default autoscaling mechanism.

The important point is that **all of these approaches can run on Kubernetes**.

The difference is the serving layer:

```text
FastAPI

   → application-level serving

BentoML

   → ML-focused application serving

KServe Standard

   → Kubernetes-native ML serving using standard

     Kubernetes resources

KServe + Knative

   → Kubernetes-native ML serving plus Knative's

     serverless serving capabilities
```

---

## What HousePred demonstrates

HousePred intentionally serves the same model through different serving layers:

```text
FastAPI

   ↓

application-level serving

BentoML

   ↓

ML-focused application serving

KServe Standard

   ↓

Kubernetes-native ML serving

KServe + Knative

   ↓

Kubernetes-native ML serving

+

serverless/request-driven serving

+

scale-to-zero

+

Revision traffic management
```

The project demonstrates the progression from **building the serving application using a web framework**, to using an **ML-serving framework**, to using a **Kubernetes-native ML-serving platform**, and finally to adding **serverless serving capabilities through Knative**.
