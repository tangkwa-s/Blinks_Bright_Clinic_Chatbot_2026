"""Channel adapter — outbound delivery for the web chat.

The web channel is delivered to the browser over WebSocket by the messaging
pipeline, so its adapter is a no-op. It is kept behind ``get_adapter`` so every
sender (AI replies, broadcasts, notices) goes through one delivery call.
"""


class ChannelAdapter:
    channel = "base"

    def send(self, db, conversation, customer, text: str) -> bool:
        """Deliver ``text``; return True if it actually reached the customer."""
        raise NotImplementedError

    def typing(self, db, conversation, customer) -> None:
        """Show a native 'AI is typing' effect while the reply is generated."""
        return


class WebAdapter(ChannelAdapter):
    channel = "web"

    def send(self, db, conversation, customer, text: str) -> bool:
        # Delivered to the browser via WebSocket by the pipeline — always reaches the web inbox.
        return True


def get_adapter(channel: str) -> ChannelAdapter:
    return WebAdapter()
