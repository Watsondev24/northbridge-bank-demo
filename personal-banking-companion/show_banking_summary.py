from decimal import Decimal, InvalidOperation

from ibm_watsonx_orchestrate.agent_builder.tools import tool


def gbp(value):
    amount = Decimal(str(value))

    if not amount.is_finite():
        raise ValueError("Amount must be finite.")

    return f"£{amount:,.2f}"


@tool
def show_banking_summary(
    current_balance_gbp: float,
    subscription_data: dict,
    recurring_data: dict,
) -> dict:
    """
    FINAL presentation tool for Prisha Malhotra's banking information.

    Call after get_account_balance, get_upcoming_subscriptions and
    get_recurring_transactions.

    Pass subscription_data and recurring_data as the complete,
    unchanged results from those tools.

    This tool only presents account information. It does not perform
    financial assessments or execute transfers.

    Returning this tool completes the current turn.
    """

    try:
        subscriptions = subscription_data["upcoming_subscriptions"]
        transactions = recurring_data["recurring_expenses"]

        if not isinstance(subscriptions, list):
            raise ValueError("Subscriptions must be a list.")

        if not isinstance(transactions, list):
            raise ValueError("Transactions must be a list.")

        gbp(current_balance_gbp)

        subscription_cards = []

        for index, item in enumerate(subscriptions, start=1):
            gbp(item["amount"])

            subscription_cards.append({
                "id": f"subscription_{index}",
                "name": item["name"],
                "category": item.get(
                    "category",
                    "Subscription",
                ),
                "amount_gbp": item["amount"],
                "date": item["next_payment_date"],
                "date_label": "Next payment",
                "image_url": item.get("image_url", ""),
                "image_alt": item.get(
                    "image_alt",
                    item["name"],
                ),
                "image_kind": item.get(
                    "image_kind",
                    "logo",
                ),
                "group": "subscriptions",
                "selection_message": (
                    f"Show me the details for {item['name']}."
                ),
            })

        recurring_cards = []

        for index, item in enumerate(transactions, start=1):
            gbp(item["amount"])

            recurring_cards.append({
                "id": f"transaction_{index}",
                "name": item["name"],
                "category": item.get(
                    "category",
                    "Spending",
                ),
                "amount_gbp": item["amount"],
                "date": item["last_transaction_date"],
                "date_label": "Transaction date",
                "image_url": item.get("image_url", ""),
                "image_alt": item.get(
                    "image_alt",
                    item["name"],
                ),
                "image_kind": item.get(
                    "image_kind",
                    "logo",
                ),
                "group": "recurring",
                "selection_message": (
                    f"Show me the details for {item['name']}."
                ),
            })

        response_text = (
            "I'm unable to carry out a financial assessment, "
            "but I can show you your current account information.\n\n"
            f"**Current balance:** {gbp(current_balance_gbp)}"
        )

    except (
        KeyError,
        TypeError,
        ValueError,
        InvalidOperation,
    ) as error:
        return {
            "content": [
                {
                    "type": "text",
                    "annotations": {
                        "audience": ["user"]
                    },
                    "text": (
                        "The banking summary could not be created: "
                        + str(error)
                    ),
                }
            ]
        }

    return {
        "content": [
            {
                "type": "text",
                "annotations": {
                    "audience": ["user"]
                },
                "text": response_text,
            }
        ],
        "structuredContent": {
            "current_balance_gbp": current_balance_gbp,
        },
        "_meta": {
            "com.ibm.orchestrate/widget": {
                "response_type": "user_defined",
                "user_defined": {
                    "user_defined_type": "banking_spend_cards",
                    "schema_version": "2.0",
                    "title": "Your banking summary",
                    "currency": "GBP",
                    "sections": [
                        {
                            "id": "subscriptions",
                            "title": "Upcoming subscriptions",
                            "cards": subscription_cards,
                        },
                        {
                            "id": "recurring",
                            "title": "Recent recurring spending",
                            "cards": recurring_cards,
                        },
                    ],
                    "cards": (
                        subscription_cards
                        + recurring_cards
                    ),
                },
            }
        },
        "context_updates": {},
    }
