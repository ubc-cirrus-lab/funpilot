# Managing Custom Handlers and Renderers with FunPilot CLI
This directory contains example custom tool-call handler and renderer implementations, along with instructions on how to register them using the FunPilot CLI. Custom handlers and renderers allow you to extend the capabilities of the FunPilot-managed agent by defining your own logic for processing data and rendering placeholders in prompts.

## Example Custom Tool-Call Handler and Renderer
The `calculator_handler.py` file defines a simple custom tool-call handler that evaluates a math expression string. The `datetime_renderer.py` file defines a custom placeholder renderer that replaces `{{.CustomPlaceHolderExample}}` in prompt templates with the current date and time string.

### Custom Tool-Call Handler
List all registered handlers:
```bash
funpilot handler list
```
Register the custom calculator handler:
```bash
funpilot handler register \
    --name calculator \
    --code calculator_handler.py \
    --description "Simple calculator: evaluates a math expression"
```
List all registered handlers again to see the new entry:
```bash
funpilot handler list
```
Get detailed information about the calculator handler:
```bash
funpilot handler get calculator
```
### Custom Template Placeholder Renderer
List all registered renderers:
```bash
funpilot renderer list
```
Register the custom datetime renderer:
```bash
funpilot renderer register \
    --name datetime_renderer \
    --placeholder CustomPlaceHolderExample \
    --code datetime_renderer.py \
    --description "Provides current date/time for {{.CustomPlaceHolderExample}}"
```
List all registered renderers again to see the new entry:
```bash
funpilot renderer list
```
Get detailed information about the datetime renderer:
```bash
funpilot renderer get datetime_renderer
```
