# Northbridge Bank | End-to-End Agent Development Lifecycle

A fictional retail-banking experience that shows how **IBM watsonx Orchestrate** and **IBM Bob** work together across the **entire Agent Development Lifecycle**: discover a missing capability using the **Control Plane**, build a specialist agent using **Bob**, test it through **ADK red-teaming**, introduce **Controls and custom guardrails**, deploy the improved experience, and return to observability to monitor how it performs.

**Identify → Build → Test → Govern → Deploy → Monitor**

> **Fictional demonstration:** Northbridge Bank, its balances, transactions and financial assessments are illustrative. This is not financial advice or a production banking application. The screenshots depict a staged demo, not evidence that all the stages have been completed by the files in this repository.

## The story: From customer frustration to a governed agent

A customer wants to send **£500 to a friend** and asks the Northbridge Bank Personal Banking Companion whether they can afford it. The companion can retrieve a balance, upcoming subscriptions and spending history, but cannot assess affordability. The answer leaves the customer frustrated: the banking experience looks polished, but the agent lacks the capability the customer actually needs.

The bank's team investigates the conversation in **watsonx Orchestrate Observability / Control Plane**. Rather than guessing what went wrong, they inspect the interaction and feedback to pinpoint the missing skill. They then ask **IBM Bob** to build a new financial assessment agent and calculation tool, drawing on the existing banking assets where possible. That agent can become a collaborator of the customer-facing companion in **watsonx Orchestrate**.

Before considering it ready for customers, the team runs **red-team simulations** to stress-test agent behaviour, reviews any successful attacks, and uses **built-in Controls and custom pre-/post-invocation guardrails** as part of a broader remediation and validation process. The story closes by testing the improved customer journey and returning to the Control Plane for ongoing visibility.

IBM Bob is **required**, not optional, for the *build* stage of this demonstration. watsonx Orchestrate is required for the *run, observe, evaluate and govern* stages.

## Visual walkthrough

These are screenshots from the presentation flow. They are included as illustrations; the included source files and v3 guardrail reference code need configuring and validation in your own environment.

### 1. Customer-facing banking experience

![Northbridge Bank banking website](docs/images/01-banking-home.webp)

The user opens the Northbridge Bank frontend and asks a £500 transfer-affordability question through the watsonx Orchestrate chat widget. The initial Personal Banking Companion is restricted to retrieving and displaying financial information.

### 2. Identify the problem in the Control Plane

![Personal Banking Companion conversation observed in watsonx Orchestrate](docs/images/02-control-plane-observability.webp)

The team inspects the conversation in **Observability → Conversations**, including the inability to assess affordability and a subsequent frustrated message. This provides evidence of the customer-experience gap that the new capability should address. The screenshot shows a conversation, not a quantified sentiment trend across all users.

### 3. Build with IBM Bob

![IBM Bob drafting the financial assessment agent](docs/images/03-bob-build-agent.webp)

Bob receives a natural-language request to build a Financial Assessment Agent: reuse existing banking data where possible, assess available balance and commitments, calculate the remaining buffer, and expose the new capability to the Personal Banking Companion.

### 4. Bring the agents together in Orchestrate

![Personal Banking Companion and financial assessment agent in Orchestrate](docs/images/04-agents-in-orchestrate.webp)

The Orchestrate catalogue shows the original companion and new assessment agent. In the staged demo, the companion has one connected agent. **The YAMLs in this repository are earlier starting versions**: the companion YAML still lists `collaborators: []`; the source assessment agent is named `financial_advisor_agent`, whereas the screenshot shows `financial_assessment_agent`. Update the agent name, instructions and collaborator registration consistently before reproducing this stage.

### 5. Run red-team simulations

![ADK red-teaming simulation output](docs/images/05-red-team-results.webp)

The demo launches adversarial tests such as instruction override, jailbreaking, unsafe topics and prompt leakage. The captured output includes successful on-policy attacks. Such results must be investigated; they do not by themselves show the agent is secure or that subsequent controls fixed every weakness.

### 6. Apply built-in and custom Controls

![Orchestrate Controls landing page](docs/images/06-controls-overview.webp)

![Creating an Orchestrate control](docs/images/07-create-control.webp)

The governance stage explores built-in content guardrails and other control types, together with the supplied **custom language guardrail**. The v3 example uses a pre-invoke check to track violations and a post-invoke hook to append a warning after the first occurrence of the word `silly`. A second occurrence in the same identified conversation is intended to stop processing. Actual warning rendering and block handling must be verified in the target environment.

### 7. Validate and revisit the banking experience

![Personal Banking Companion agent preview](docs/images/08-agent-validation.webp)

![Return to the Northbridge Bank customer experience](docs/images/09-banking-return.webp)

Test the agent interactions and safeguards, then return to the banking frontend to ask the original affordability question again. The intended outcome is a specialist assessment via the collaborator, with ongoing monitoring in the Control Plane. These screenshots show the preview and return to the frontend; they **do not capture a completed final £500 assessment**.

## Components at a glance

| Component | Role in the story |
| --- | --- |
| **Agent 1 — Personal Banking Companion** | Customer-facing agent for account balance, subscriptions and recent recurring transactions. Initially cannot offer affordability assessments. |
| **Agent 2 — Financial Assessment Agent** | Specialist for analysing a proposed transfer or purchase and the remaining financial buffer. |
| **IBM Bob** | Builds or adapts Agent 2 and its calculation capability using natural-language development instructions. |
| **watsonx Orchestrate** | Hosts and coordinates agents and provides observability, evaluation, governance and Controls. |
| **ADK red teaming** | Generates and runs simulated attacks to uncover behaviour that needs remediation. |
| **Language guardrails** | Illustrative pre- and post-invocation custom controls and two-strike behaviour. |

## Repository contents

- **`docs/images/`**: Sanitised presentation screenshots illustrating the seven-step narrative.

- **`personal-banking-companion/`**: `personal_banking_companion.yaml` and four tools for balance, subscriptions, recurring transactions and summary rendering.
- **`financial-advisor-agent/`**: `financial_advisor_agent.yaml` and `assess_transfer_risk.py` for transfer risk analysis. The source agent is named `financial_advisor_agent`, even though this guide calls it the Financial Assessment Agent (Agent 2).
- **`controls/language_guardrail_plugin_openapi.yaml`:** OpenAPI definition of a custom pre-invocation language guardrail. Its Python FastAPI implementation is in `controls/language_guardrail_plugin.py`.
- **`frontend/northbridge-bank.html`:** The Northbridge Bank customer-facing website and optional watsonx Orchestrate chat widget integration.

## Prerequisites

**Both IBM Bob and IBM watsonx Orchestrate are required to follow the full use case.** Bob is used to build or extend the Financial Assessment Agent (Agent 2), and watsonx Orchestrate is used to deploy, connect and run the banking agents. The central purpose of the demo is to showcase how these products work together, rather than present Bob as an optional extra.

- [Try IBM watsonx Orchestrate](https://www.ibm.com/products/watsonx-orchestrate) — select **Try it free**.
- [Get an IBM Bob free trial](https://bob.ibm.com/trial) — required for the Agent 2 development portion of this demo.
- [watsonx Orchestrate documentation](https://www.ibm.com/docs/en/watsonx/watson-orchestrate/base)

*Free trials require registration and are subject to IBM's current eligibility and trial terms.*

## Set up the agents

1. Set up access to **both IBM Bob and IBM watsonx Orchestrate**.
2. Review the supplied agent definitions and tools; configure integrations and environment variables for your own environment.
3. Import and deploy **Agent 1: Personal Banking Companion** and its supporting tools in watsonx Orchestrate.
4. Use **IBM Bob to build or adapt Agent 2: Financial Assessment Agent**, using the supplied agent assets as reference. Review and test its tools before deployment.
5. Deploy Agent 2 to **watsonx Orchestrate**. Add `financial_advisor_agent` to the Personal Banking Companion's collaborators list, update its instructions to invoke the collaborator for assessment requests, then reimport Agent 1. This integration is **not yet defined** in the supplied Agent 1 YAML.
6. Test the end-to-end experience: account retrieval, subscriptions and recurring transactions through Agent 1, followed by financial assessment using Agent 2. Use fictional data only.

## Import commands

Run from the repository root in a configured watsonx Orchestrate ADK environment. Import the Python tools before their agents:

```bash
orchestrate tools import -f personal-banking-companion/get_account_balance.py --kind python
orchestrate tools import -f personal-banking-companion/get_upcoming_subscriptions.py --kind python
orchestrate tools import -f personal-banking-companion/get_recurring_transactions.py --kind python
orchestrate tools import -f personal-banking-companion/show_banking_summary.py --kind python
orchestrate tools import -f financial-advisor-agent/assess_transfer_risk.py --kind python

orchestrate agents import -f personal-banking-companion/personal_banking_companion.yaml
orchestrate agents import -f financial-advisor-agent/financial_advisor_agent.yaml
```

The supplied tools use illustrative account data. The provided YAMLs do not yet implement the complete connected end-to-end story.

## Red-team the agents with watsonx Orchestrate ADK

Run vulnerability testing **before** approving a new agent for deployment. The ADK supports on-policy attacks tailored to an agent's instructions and off-policy attacks that test more general weaknesses such as prompt leakage. These are simulated attacks, not a security certification.

Official guide: [IBM — LLM agent vulnerability testing](https://developer.watson-orchestrate.ibm.com/evaluate/llm_vulnerability).

1. Ensure the ADK is installed and configured, the target native agent is imported in your active environment, and an evaluation dataset has been created following IBM's [evaluation dataset documentation](https://developer.watson-orchestrate.ibm.com/evaluate/llm_vulnerability).
2. Check supported attack types:

   ```bash
   orchestrate evaluations red-teaming list
   ```

3. Create attack scenarios (replace `PATH_TO_EVALUATION_DATASET.json` with your actual dataset). The `-g` directory must contain the target agent YAML:

   ```bash
   orchestrate evaluations red-teaming plan \
     -a "Instruction Override, Jailbreaking, Unsafe Topics, Crescendo Prompt Leakage" \
     -d PATH_TO_EVALUATION_DATASET.json \
     -g financial-advisor-agent \
     -t financial_advisor_agent \
     -n 1
   ```

4. Run the generated attacks (default attack output folder shown; use the actual path displayed by your `plan` command):

   ```bash
   orchestrate evaluations red-teaming run -a red_teaming_attacks/
   ```

5. Review which attacks were resisted or successful. Address findings through stronger instructions, tool permissions, relevant controls or guardrail plugins, then **run the evaluation again**. Keep the results for comparison.

IBM currently documents this feature for **native agents**. Some attack types, datasets, models or environments may require additional configuration. Follow the linked guide if command options change.

## Add the custom language guardrail

The included `controls/language_guardrail_plugin_openapi.yaml` describes a **pre-invocation plugin** (`agent_pre_invoke`, operation `language_guardrail_pre`). It detects the word `silly` (case-insensitive) in the latest message and adds a gentle reminder to the agent to acknowledge frustration, encourage respectful language and still address the original request.

**Important:** The current Python implementation always returns `continue_processing: true`. It **never blocks requests**, does **not** count repeat offences or maintain conversation state, and relies on the agent to follow the inserted guidance. The OpenAPI YAML describes the API contract, while the FastAPI service implements its behaviour. A reachable HTTPS endpoint is required for an Orchestrate deployment.

To connect your implementation:

1. Install dependencies and start the FastAPI service **from the repository root**:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r controls/requirements.txt
   python -m uvicorn language_guardrail_plugin:app --app-dir controls --host 127.0.0.1 --port 8000
   ```

   Locally you can inspect `http://127.0.0.1:8000/docs` and test `POST /agent_pre_invoke`. This local endpoint is **not accessible** from the cloud Orchestrate service.
2. Deploy or expose the service at a stable public HTTPS endpoint reachable by watsonx Orchestrate, and secure it appropriately.
3. Replace `https://YOUR_GUARDRAIL_HOST.example.com` in the OpenAPI `servers` entry with your service's public HTTPS URL. Do not commit temporary ngrok session URLs or credentials.
4. Import or configure the OpenAPI-based custom plugin using the **Plugins/Controls** experience in watsonx Orchestrate, and attach the plugin to the intended agent.
5. Test an ordinary request and a request containing `silly`, verifying that the service returns `continue_processing: true` and adds `modified_payload` guidance for a matching message. Repeat-offence blocking is **not supported** by this version.
6. Use the red-team workflow above to validate that relevant protections hold under more varied attacks.

This example illustrates the difference between **built-in Controls** and **custom pre-invocation plugins**. For the full demonstration, show how red-team findings inform which safeguards you enable, and then repeat the tests to validate their effect.

## v3 pre-invoke and post-invoke language controls

The `controls/` folder also contains two **v3 OpenAPI control specifications**:

- `language_guardrail_pre_v3.yaml` — `agent_pre_invoke` monitors the incoming message and blocks a repeat violation.
- `language_guardrail_post_v3.yaml` — `agent_post_invoke` can add an explicit warning after the initial violation.

The supplied v3 YAMLs are your original specifications with the personal ngrok hostname **replaced by `https://YOUR_GUARDRAIL_HOST.example.com`**. They are API schemas, not executable controls.

`language_guardrail_v3.py` is a **new reference implementation reconstructed from the expected behaviour you described**, not your original missing v3 Python file. Treat it as demonstration code: actual request/response payload shapes and wxO handling of blocked responses must be tested against your environment. This implementation uses SQLite to track violations by explicit conversation/session ID and does **not** treat an absent ID as a shared global session.

### Start the v3 service

Terminal 1, from the project root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r controls/requirements.txt
python -m uvicorn language_guardrail_v3:app --app-dir controls --port 8000
```

Terminal 2: expose port 8000 through a secure HTTPS tunnel or deployment that wxO can reach (for example, `ngrok http 8000`). Update the `servers` URL **locally** in **both** v3 YAML files, then import/register them as pre- and post-invocation plugins in watsonx Orchestrate. Do not commit your active tunnel URL. Keep both Terminal windows running for the demo.

### Expected tests

Use the **same conversation ID** for the first two messages:

| Message | Expected action |
| --- | --- |
| `Ugh, this is so silly.` | First occurrence: pre-invoke allows processing; post-invoke attempts to add a warning. |
| `This is still silly.` | Second occurrence: pre-invoke responds with `continue_processing: false`; agent processing should stop if this response is honoured by wxO. |

Use a **distinct conversation identifier** to start a fresh session. If a new conversation appears blocked on its first violation, inspect the ID and SQLite strike data. Restarting Python **does not** reset SQLite. The demo's default DB is `~/.northbridge_guardrail_strikes.sqlite3` (override using `GUARDRAIL_DB_PATH`). Deleting this DB is a **manual demo reset** and erases all saved strike counts; do not do so while the service is running. If wxO does not pass an identifier at the top-level request context/payload, adapt `_conversation_id` to the actual event shape before relying on this behaviour.

This reference service does not include production authentication, concurrency across multiple processes, automated retention, or exhaustive language classification. Verify actual warning rendering and blocking in your target Orchestrate environment.

## Run the frontend

The frontend is a self-contained HTML demo file. Open `frontend/northbridge-bank.html` in a browser, or serve it locally:

```bash
cd frontend
python3 -m http.server 8000
```

Then visit [http://localhost:8000/northbridge-bank.html](http://localhost:8000/northbridge-bank.html).

### Connect your own watsonx Orchestrate agent

The HTML includes an **optional** embedded chat widget. All original instance-specific identifiers have been replaced with placeholders. Find the `window.wxOConfiguration` block near the end of `frontend/northbridge-bank.html` and replace:

| Placeholder | Replace with |
| --- | --- |
| `REPLACE_WITH_YOUR_ORCHESTRATION_ID` | Your watsonx Orchestrate orchestration ID |
| `REPLACE_WITH_YOUR_INSTANCE_CRN` | The CRN for your watsonx Orchestrate instance |
| `REPLACE_WITH_YOUR_AGENT_ID` | Your deployed banking agent's ID |
| `https://YOUR_REGION.watson-orchestrate.cloud.ibm.com` | Your environment's host URL |

The relevant structure is:

```javascript
window.wxOConfiguration = {
  orchestrationID: 'REPLACE_WITH_YOUR_ORCHESTRATION_ID',
  hostURL: 'https://YOUR_REGION.watson-orchestrate.cloud.ibm.com',
  rootElementID: 'root',
  deploymentPlatform: 'ibmcloud',
  crn: 'REPLACE_WITH_YOUR_INSTANCE_CRN',
  chatOptions: {
    agentId: 'REPLACE_WITH_YOUR_AGENT_ID'
    // Other UI settings are retained in the supplied HTML.
  }
};
```

The page can be viewed as a frontend demo without completing the widget configuration, but **the chat widget will not connect** until valid configuration values and any required access settings are supplied. Do not commit API keys, authentication tokens or private customer data to a public repository.



## Disclaimer

This is an educational demonstration of agent orchestration and a fictional banking interface, not a production banking system. Before using a similar pattern with real financial data, implement appropriate security, authentication, testing, oversight and regulatory controls.
