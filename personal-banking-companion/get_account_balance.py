from ibm_watsonx_orchestrate.agent_builder.tools import tool


@tool
def get_account_balance(account_holder_name: str) -> dict:
    """
    Retrieves the current account balance and available funds
    for the authenticated user.

    Args:
        account_holder_name: Full name of the account holder.

    Returns:
        Current balance, available funds and account metadata.
    """

    return {
        "account_holder": account_holder_name,
        "account_number": "****4821",
        "account_type": "Current Account",
        "sort_code": "20-14-63",
        "current_balance_gbp": 1482.60,
        "available_balance_gbp": 1482.60,
        "overdraft_limit_gbp": 500.00,
        "currency": "GBP",
        "status": "active",
        "last_updated": "2025-09-05T23:10:00Z",
    }
