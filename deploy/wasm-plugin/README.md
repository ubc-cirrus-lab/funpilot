# FunPilot Wasm Plugin for Istio Ingress
FunPilot provides a Wasm plugin that can be deployed in Istio ingress to collect and report additional request metrics for a richer context in FunPilot's diagnosis and remediation pipeline. This Wasm plugin is designed to be lightweight and efficient, and is optional to use with FunPilot.

## Usage
Deploy the Wasm plugin in your Istio ingress by applying the provided Kubernetes manifest:
```bash
kubectl apply -f funpilot-wasm-plugin.yaml
```
