# FunPilot CLI
FunPilot provides a command-line interface (CLI) for configuring and managing FunPilot-related resources, such as target applications, system configurations, placeholder renderers, and tool-call handlers.
The CLI serves as the primary user-facing interface to the system without requiring users to interact directly with the underlying Kubernetes objects or control-plane internals.
Through the CLI, users can authenticate with the system, manage target applications, create and inspect FunPilot configurations, compile natural-language SLOs into FunPilot configurations, manage user-defined agentic workflows, placeholder renderers, tool-call handlers, and query user-level and application-level token usage.

## CLI Installation
We provide a compiled binary release of the FunPilot CLI for Linux (amd64). You can install the CLI by downloading the binary to your local machine. For example

```bash
curl -L -o funpilot https://raw.githubusercontent.com/ubc-cirrus-lab/funpilot/refs/heads/main/cli/funpilot
chmod +x funpilot
./funpilot --help
```

Optionally, you can move the binary to a directory in your system PATH for easier access:

```bash
sudo mv funpilot /usr/local/bin/
funpilot --help
```

## CLI Usage
After installing the CLI, you can use it to interact with your FunPilot deployment.
You can run `funpilot --help` to see the available commands and options. Each command also has its own help message that you can access with `funpilot <command>`.

For example, you can use the following commands manage your applications and configurations:
Login into the system:
```bash
funpilot login
```
The CLI will prompt you to enter your authentication token. Please refer to the configuration bootstrapping instructions for pre-seeded user credentials.
List all available configurations:
```bash
funpilot config list
```
Get detailed information about a specific configuration:
```bash
funpilot config get default-funpilot-config
```
Get a specific field from a configuration:
```bash
funpilot config get default-funpilot-config workflow_name
```
Set a specific field in a configuration:
```bash
funpilot config set default-funpilot-config workflow_name oneshot
```
Deploy an application using a specific configuration:
```bash
funpilot app deploy -f example-app.yaml -c default-funpilot-config
```
List all deployed applications:
```bash
funpilot app list
```
Disable the FunPilot feature for an application:
```bash
funpilot app disable user-1-app-1
```
Enable the FunPilot feature for an application with a specific configuration:
```bash
funpilot app enable user-1-app-1 -c default-funpilot-config
```
Delete an application:
```bash
funpilot app delete user-1-app-1
```
