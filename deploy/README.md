# Deploy FunPilot

We provide ready-to-use FunPilot images and Kubernetes manifests to make it easy for you to deploy FunPilot in your cluster. You can use the following instructions to deploy FunPilot to your Kubernetes cluster. This will set up the necessary RBAC permissions, secrets, database, and FunPilot.

## Prerequisites
The following infrastructure, middleware, and observability components are required to before deploying FunPilot
* Kubernetes >= 1.31
* Knative >= 1.19
* Grafana Stack >= 12.1
* Istio >= 1.27
    * Both ambient and sidecar modes are supported
    * Istio Ingress Gateway
    * Istio [Wasm Plugin](./wasm-plugin) recommended but not required
* Cluster load balancer or MetalLB for exposing the API endpoint (recommended but not required)

We did not test FunPilot on earlier versions of Kubernetes and Knative, but it may work on slightly older versions as well.

## Installation Steps

Create the `funpilot` namespace in your cluster:
```Bash
kubectl create ns funpilot
```

Deploy FunPilot to your cluster using the provided Kubernetes manifests:
```Bash
kubectl apply -f funpilot-rbac.yaml
kubectl apply -f funpilot-config.yaml
kubectl apply -f funpilot-secrets.yaml
kubectl apply -f funpilot-config-api.yaml
kubectl apply -f funpilot-deployment.yaml
```
Wait for the FunPilot pod to be up and running. You can check the status of the pod using the following command:
```Bash
watch "kubectl get pods -n funpilot"
```

Once all pods are in the `Running` state, FunPilot should be successfully deployed in your cluster. You can check the logs of the FunPilot pod to verify that it is running correctly:
```Bash
kubectl logs -n funpilot -l app=funpilot
```
