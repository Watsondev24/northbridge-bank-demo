from datetime import datetime, timezone

from ibm_watsonx_orchestrate.agent_builder.tools import tool


@tool
def get_upcoming_subscriptions() -> dict:
    """
    Retrieve Prisha Malhotra's upcoming subscription payments.

    Returns:
        Upcoming subscriptions due within the next 30 days.
    """

    today = datetime.now(timezone.utc).date()

    subscriptions = [
        {
            "name": "Spotify",
            "amount": 9.99,
            "category": "Music",
            "image_alt": "Spotify merchant image",
            "image_url": (
                "https://www.google.com/s2/favicons"
                "?domain=spotify.com&sz=128"
            ),
            "image_kind": "logo",
            "next_payment_date": today.replace(day=11).isoformat(),
        },
        {
            "name": "Netflix",
            "amount": 15.99,
            "category": "Entertainment",
            "image_alt": "Netflix merchant image",
            "image_url": (
                "https://www.google.com/s2/favicons"
                "?domain=netflix.com&sz=128"
            ),
            "image_kind": "logo",
            "next_payment_date": today.replace(day=14).isoformat(),
        },
        {
            "name": "Mandarin Oriental Gym Membership",
            "amount": 210.00,
            "category": "Fitness",
            "image_alt": "Mandarin Oriental Gym Membership merchant image",
            "image_url": (
                "https://media.ffycdn.net/eu/"
                "mandarin-oriental-hotel-group/"
                "aq2hRUD5Tfpkof5hz3A9.jpg"
            ),
            "image_kind": "photo",
            "next_payment_date": today.replace(day=18).isoformat(),
        },
    ]

    total_due = sum(item["amount"] for item in subscriptions)

    return {
        "as_of_date": today.isoformat(),
        "currency": "GBP",
        "total_due_gbp": round(total_due, 2),
        "upcoming_subscriptions": subscriptions,
        "window_days": 30,
    }
