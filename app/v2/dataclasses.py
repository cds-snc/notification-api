from dataclasses import dataclass


@dataclass
class V2PushPayload:
    app_sid: str
    template_id: str
    icn: str | None = None
    topic_sid: str | None = None
    personalisation: dict[str, str] | None = None

    def is_valid(self) -> bool:
        """Identify if the payload is valid

        Returns:
            bool: True if valid
        """
        # icn alone means it's push. topic_sid alone means broadcast. Cannot be both.
        return (self.icn and self.topic_sid is None) or (self.topic_sid and self.icn is None)

    def is_broadcast(self) -> bool:
        """Identify if the payload is a broadcast

        Returns:
            bool: True if it is a broadcast
        """
        return self.topic_sid is not None
