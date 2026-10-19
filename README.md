# Northbridge Bank | Agentic Banking Demo

An interactive banking demo showcasing **IBM Bob and IBM watsonx Orchestrate working together**: Bob accelerates development of a new specialist agent, while watsonx Orchestrate enables agent deployment and collaboration in the banking experience. It includes a customer-facing banking companion, a separate financial assessment agent, and a browser-based Northbridge Bank frontend.

> **Demo only.** Northbridge Bank is fictional. Any accounts, balances, transactions and assessments used for demonstration are not real financial services or financial advice.

## What you'll build

| Order | Agent | Responsibility |
| --- | --- | --- |
| **Agent 1** | **Personal Banking Companion** | Retrieves and presents account information, upcoming subscriptions and recurring transactions using the available tools. It does not independently perform affordability or risk assessments. |
| **Agent 2** | **Financial Assessment Agent** | Adds financial assessment capabilities, using its assessment tools and the banking information available to it. |

The demonstration is designed to show the combined value of **IBM Bob for building the Financial Assessment Agent** and **watsonx Orchestrate for running and orchestrating both agents**. The two-agent design keeps **information retrieval** separate from **financial assessment**. The companion answers straightforward banking questions; the assessment agent is designed to handle requests that require additional calculations or judgement once collaboration is configured. The provided agent definitions are a starting point. **The Personal Banking Companion currently has `collaborators: []`**, so Agent 2 must be registered as a collaborator and its instructions updated to delegate assessment requests before the fully connected flow will work.

## Repository contents

- **`personal-banking-companion/`**: `personal_banking_companion.yaml` and four tools for balance, subscriptions, recurring transactions and summary rendering.
- **`financial-advisor-agent/`**: `financial_advisor_agent.yaml` and `assess_transfer_risk.py` for transfer risk analysis. The source agent is named `financial_advisor_agent`, even though this guide calls it the Financial Assessment Agent (Agent 2).
- **`frontend/northbridge-bank.html`:** The Northbridge Bank customer-facing website and optional watsonx Orchestrate chat widget integration.

## Prerequisites

**Both IBM Bob and IBM watsonx Orchestrate are required to follow the full use case.** Bob is used to build or extend the Financial Assessment Agent (Agent 2), and watsonx Orchestrate is used to deploy, connect and run the banking agents.
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

## Example walkthrough

1. Ask the **Personal Banking Companion** for a summary of your account and upcoming subscriptions.
2. Highlight how **IBM Bob** is used to create the additional financial assessment capability in **Agent 2**.
3. Deploy and connect Agent 2 in **watsonx Orchestrate**, then ask a question that requires financial assessment.
4. Demonstrate the updated experience, where the agents collaborate, and explain how **Bob accelerates building new functionality** while **Orchestrate operationalises and governs the agents**.

## Disclaimer

This is an educational demonstration of agent orchestration and a fictional banking interface, not a production banking system. Before using a similar pattern with real financial data, implement appropriate security, authentication, testing, oversight and regulatory controls.
