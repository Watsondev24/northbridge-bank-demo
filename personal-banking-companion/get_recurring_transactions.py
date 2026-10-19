from calendar import monthrange
from datetime import datetime, timedelta, timezone

from ibm_watsonx_orchestrate.agent_builder.tools import tool


@tool
def get_recurring_transactions(
    account_data: dict,
    subscription_data: dict,
    merchant_name: str = "",
) -> dict:
    """
    Retrieve Prisha Malhotra's recent recurring transaction history.

    Call after get_account_balance and get_upcoming_subscriptions.

    Args:
        account_data: Complete unchanged result from get_account_balance.
        subscription_data: Complete unchanged result from
            get_upcoming_subscriptions.
        merchant_name: Optional exact merchant name used to filter results.

    Returns:
        Recent recurring transaction data.
    """

    today = datetime.now(timezone.utc).date()

    latest_end = today.replace(day=1) - timedelta(days=1)
    latest_month = latest_end.replace(day=1)

    earlier_month = (
        latest_month - timedelta(days=1)
    ).replace(day=1)

    def transaction_date(month, day):
        day = min(day, monthrange(month.year, month.month)[1])
        return month.replace(day=day).isoformat()

    rows = [
        (
            "Harry's Dolce Vita Knightsbridge",
            "Dining",
            68.50,
            latest_month,
            18,
            "harrys.co.uk",
        ),
        (
            "British Airways",
            "Travel",
            132.00,
            latest_month,
            26,
            "britishairways.com",
        ),
        (
            "Four Seasons London",
            "Accommodation",
            198.75,
            latest_month,
            27,
            "fourseasons.com",
        ),
        (
            "Harry's Dolce Vita Knightsbridge",
            "Dining",
            92.30,
            earlier_month,
            19,
            "harrys.co.uk",
        ),
        (
            "Four Seasons London",
            "Accommodation",
            255.50,
            earlier_month,
            30,
            "fourseasons.com",
        ),
    ]

    transactions = [
        {
            "name": name,
            "category": category,
            "amount": amount,
            "last_transaction_date": transaction_date(month, day),
            "image_url": (
                f"https://www.google.com/s2/favicons"
                f"?domain={domain}&sz=128"
            ),
            "image_kind": "logo",
        }
        for name, category, amount, month, day, domain in rows
    ]

    transactions.sort(
        key=lambda item: item["last_transaction_date"],
        reverse=True,
    )

    selected = merchant_name.strip().casefold()

    if selected:
        transactions = [
            item
            for item in transactions
            if item["name"].casefold() == selected
        ]

    return {
        "recurring_expenses": transactions,
        "period_start": earlier_month.isoformat(),
        "period_end": latest_end.isoformat(),
    }
