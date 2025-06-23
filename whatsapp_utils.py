
from twilio.rest import Client
import streamlit as st

def send_whatsapp_message(message_body: str, to_number: str = None) -> str:
    """
    Sends a WhatsApp message using Twilio.

    Args:
        message_body (str): Message content
        to_number (str, optional): WhatsApp number (format: +972...). Defaults to WHATSAPP_TO from secrets.

    Returns:
        str: Message SID if sent
    """
    account_sid = st.secrets["TWILIO_SID"]
    auth_token = st.secrets["TWILIO_AUTH_TOKEN"]
    from_whatsapp_number = st.secrets["WHATSAPP_FROM"]
    to_whatsapp_number = to_number if to_number else st.secrets["WHATSAPP_TO"]

    client = Client(account_sid, auth_token)
    message = client.messages.create(
        body=message_body,
        from_=from_whatsapp_number,
        to=to_whatsapp_number
    )
    return message.sid
