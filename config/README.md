# Bootstrap the Initial Configuration for FunPilot

## Example FunPilot Configuration
We provide a Python script to bootstrap the initial configuration for FunPilot. The script seeds the configuration store with an example FunPilot setup configuration can be used as a starting point for deployment and customization.

The script initializes example alert rules, metric definitions, agent definitions,
prompt templates, and built-in components required to run the system.

The bootstrapped example includes five agent definitions. These agents include:
* `triage-propose-judge`: a multi-stage workflow presented in the manuscript, which performs triage, proposal, and judgment in separate steps.
* `oneshot`: a single-step workflow that directly analyzes the context and outputs proposed changes.
* `fixed-update`: a testing workflow that always generates a fixed CPU-limit update.
* `toolcall-example`: a testing workflow that applies a fixed update through a tool-call handler without an LLM call.
* `custom-handler-demo`: an example workflow showing how custom handlers and custom placeholder renderers can be integrated into the user-defined agentic workflow.

The provided configuration is intended as a reference template of FunPilot configuration.
Users can extend or replace the default agent definitions, prompts, guardrails, and evaluation logic to match their own serverless applications and operational goals.

Please note that the this configuration is intended for demonstration purposes. This artifact includes simplified prompt templates sufficient to demonstrate the FunPilot workflow.  
The full prompts used in our internal experiments are not released in this repository.

## Load the Configuration
Please run the following commands to load the initial configuration into your FunPilot deployment. 

Forward the database port and run the `load_init_config.py` script to seed the configuration data:
```bash
kubectl port-forward svc/funpilot-redis 46379:6379 -n funpilot >/dev/null 2>&1 &
PF_PID=$!
until nc -z localhost 46379; do
  sleep 0.2
done
python3 load_init_config.py
kill $PF_PID
wait $PF_PID 2>/dev/null
```
After bootstrapping, you can use the CLI to inspect the loaded configuration, deploy the example application, and test the end-to-end workflow. Please refer to the CLI documentation for detailed commands and usage examples. For example, you can log in as `user-1` using the pre-seeded token:

Find the configuration API endpoint:
```bash
kubectl get svc -n funpilot
```
Then set the `FUNPILOT_API_ENDPOINT` environment variable and log in:
```bash
export FUNPILOT_API_ENDPOINT=http://<external-ip>:<port>
funpilot login
```
The CLI will prompt you to enter the token for `user-1`, which is `user-1-token` as seeded by the script.
