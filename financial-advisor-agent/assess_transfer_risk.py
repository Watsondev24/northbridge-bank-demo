from ibm_watsonx_orchestrate.agent_builder.tools import tool


@tool
def assess_transfer_risk(
    transfer_amount_gbp: float,
    current_balance_gbp: float,
    total_upcoming_subscriptions_gbp: float,
    total_monthly_recurring_gbp: float,
    account_holder_name: str = "René"
):
    """
    Analyses whether a proposed transfer amount is financially safe given the user's upcoming
    outgoings, subscriptions, and recurring transactions. Returns a risk rating and recommendation.

    Args:
        transfer_amount_gbp: The amount the user is considering transferring, in GBP
        current_balance_gbp: The user's current account balance in GBP
        total_upcoming_subscriptions_gbp: Total value of upcoming subscription charges in GBP
        total_monthly_recurring_gbp: Total estimated monthly recurring spend in GBP
        account_holder_name: The full name of the account holder from login context

    Returns:
        risk_assessment: Risk rating, remaining balance after transfer, and a clear recommendation
    """

    balance_after_transfer = current_balance_gbp - transfer_amount_gbp
    total_committed_spend = total_upcoming_subscriptions_gbp + total_monthly_recurring_gbp
    buffer_after_all_spend = balance_after_transfer - total_committed_spend

    if buffer_after_all_spend >= 500:
        risk_level = "low"
        risk_label = "Low Risk"
        recommendation = (
            f"Transferring £{transfer_amount_gbp:.2f} looks comfortable. "
            f"After all upcoming charges you would still have approximately £{buffer_after_all_spend:.2f} remaining."
        )
    elif buffer_after_all_spend >= 100:
        risk_level = "medium"
        risk_label = "Medium Risk"
        recommendation = (
            f"Transferring £{transfer_amount_gbp:.2f} is possible but leaves a slim buffer of around "
            f"£{buffer_after_all_spend:.2f} after all upcoming charges. Consider whether the transfer can wait "
            f"until after your next payday."
        )
    elif buffer_after_all_spend >= 0:
        risk_level = "high"
        risk_label = "High Risk"
        recommendation = (
            f"Transferring £{transfer_amount_gbp:.2f} would leave you with only £{buffer_after_all_spend:.2f} "
            f"after all upcoming charges. This is very tight. It is worth reviewing whether any subscriptions "
            f"or recurring costs can be reduced first."
        )
    else:
        risk_level = "critical"
        risk_label = "Not Recommended"
        shortfall = abs(buffer_after_all_spend)
        recommendation = (
            f"Transferring £{transfer_amount_gbp:.2f} is not recommended. After the transfer and all upcoming "
            f"charges, you would be short by approximately £{shortfall:.2f}. Consider a smaller transfer or "
            f"cancelling a subscription to free up funds."
        )

    risk_assessment = {
        "account_holder": account_holder_name,
        "transfer_amount_gbp": transfer_amount_gbp,
        "current_balance_gbp": current_balance_gbp,
        "balance_after_transfer_gbp": round(balance_after_transfer, 2),
        "total_committed_spend_gbp": round(total_committed_spend, 2),
        "buffer_after_all_spend_gbp": round(buffer_after_all_spend, 2),
        "risk_level": risk_level,
        "risk_label": risk_label,
        "recommendation": recommendation,
        "safe_to_transfer": risk_level in ["low", "medium"]
    }

    return risk_assessment
